-- User-owned identity effect. No API gains Keycloak or journal privileges.
DO $$ BEGIN
 IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='rac_standing_sessions') THEN
  CREATE ROLE rac_standing_sessions NOLOGIN;
 END IF;
END $$;

CREATE TABLE standing.session_effect (
 event_id uuid PRIMARY KEY REFERENCES standing.outbox(event_id) ON DELETE CASCADE,
 subject_id uuid NOT NULL REFERENCES public.usuario(id) ON DELETE CASCADE,
 version bigint NOT NULL CHECK(version>1),
 keycloak_subject text NOT NULL CHECK(length(keycloak_subject) BETWEEN 1 AND 255),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN('pending','captured','completed','superseded')),
 sessions jsonb,
 next_index integer NOT NULL DEFAULT 0 CHECK(next_index>=0),
 claim_token uuid,
 claimed_until timestamptz,
 failures integer NOT NULL DEFAULT 0 CHECK(failures BETWEEN 0 AND 8),
 due_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 completed_at timestamptz,
 UNIQUE(subject_id,version),
 CHECK((claim_token IS NULL)=(claimed_until IS NULL)),
 CHECK((state IN('completed','superseded'))=(completed_at IS NOT NULL)),
 CHECK(sessions IS NULL OR (jsonb_typeof(sessions)='array' AND jsonb_array_length(sessions)<=4096)),
 CHECK((sessions IS NULL AND next_index=0 AND state IN('pending','superseded')) OR
       (sessions IS NOT NULL AND next_index<=jsonb_array_length(sessions) AND state<>'pending'))
);
CREATE INDEX session_effect_due ON standing.session_effect(due_at,event_id)
 WHERE state IN('pending','captured');
CREATE INDEX session_effect_oldest ON standing.session_effect(created_at)
 WHERE state IN('pending','captured');

CREATE FUNCTION standing.enqueue_sessions() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 -- change_account already holds the authority account lock. All other writers
 -- use account -> effect order too. A newer version fences old work atomically.
 UPDATE standing.session_effect SET state='superseded',completed_at=clock_timestamp(),
  claim_token=NULL,claimed_until=NULL
 WHERE subject_id=NEW.subject_id AND version<NEW.standing_version AND state IN('pending','captured');
 IF NEW.payload->>'status' IN('suspended','banned') THEN
  INSERT INTO standing.session_effect(event_id,subject_id,version,keycloak_subject)
   SELECT NEW.event_id,NEW.subject_id,NEW.standing_version,u.keycloak_id
   FROM public.usuario u WHERE u.id=NEW.subject_id;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER enqueue_standing_sessions AFTER INSERT ON standing.outbox
 FOR EACH ROW EXECUTE FUNCTION standing.enqueue_sessions();

-- Do not replay historical sanctions against a now active/restricted account.
INSERT INTO standing.session_effect(event_id,subject_id,version,keycloak_subject)
 SELECT o.event_id,a.subject_id,a.version,u.keycloak_id FROM standing.account a
 JOIN public.usuario u ON u.id=a.subject_id
 JOIN standing.outbox o ON o.subject_id=a.subject_id AND o.standing_version=a.version
 WHERE a.status IN('suspended','banned');

CREATE FUNCTION standing.claim_session_effect() RETURNS TABLE(
 event_id uuid,subject_id uuid,version bigint,keycloak_subject text,
 sessions jsonb,next_index integer,claim_token uuid
) LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 WITH candidate AS (
  SELECT e.event_id FROM standing.session_effect e JOIN standing.account a ON a.subject_id=e.subject_id
  WHERE e.state IN('pending','captured') AND e.due_at<=statement_timestamp()
   AND (e.claim_token IS NULL OR e.claimed_until<=statement_timestamp())
   AND a.version=e.version AND a.status IN('suspended','banned')
  ORDER BY e.due_at,e.event_id FOR UPDATE OF e SKIP LOCKED LIMIT 1
 ), claimed AS (
  UPDATE standing.session_effect e SET claim_token=gen_random_uuid(),
   claimed_until=clock_timestamp()+interval '10 seconds'
  FROM candidate c WHERE e.event_id=c.event_id
  RETURNING e.event_id,e.subject_id,e.version,e.keycloak_subject,e.sessions,e.next_index,e.claim_token
 ) SELECT * FROM claimed;
$$;

CREATE FUNCTION standing.capture_sessions(p_event uuid,p_claim uuid,p_sessions jsonb)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 a standing.account%ROWTYPE;
 e standing.session_effect%ROWTYPE;
BEGIN
 IF p_sessions IS NULL OR jsonb_typeof(p_sessions)<>'array' OR jsonb_array_length(p_sessions)>4096 THEN
  RAISE EXCEPTION 'invalid_session_capture' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT FROM jsonb_array_elements(p_sessions) item WHERE jsonb_typeof(item)<>'object'
   OR NOT (item ?& ARRAY['id','offline']) OR (item-ARRAY['id','offline'])<>'{}'::jsonb
   OR jsonb_typeof(item->'id')<>'string' OR jsonb_typeof(item->'offline')<>'boolean'
   OR length(item->>'id') NOT BETWEEN 1 AND 256
   OR octet_length(item->>'id')<>length(item->>'id') OR (item->>'id')!~'^[!-~]+$')
 OR EXISTS(SELECT FROM jsonb_array_elements(p_sessions) item GROUP BY item HAVING count(*)>1) THEN
  RAISE EXCEPTION 'invalid_session_capture' USING ERRCODE='22023';
 END IF;
 SELECT account.* INTO a FROM standing.account account JOIN standing.session_effect effect
  ON effect.subject_id=account.subject_id WHERE effect.event_id=p_event FOR UPDATE OF account;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO e FROM standing.session_effect WHERE event_id=p_event FOR UPDATE;
 IF p_claim IS NULL OR e.claim_token IS DISTINCT FROM p_claim OR e.claimed_until<=clock_timestamp()
  OR e.state NOT IN('pending','captured') OR a.version<>e.version OR a.status NOT IN('suspended','banned') THEN
  RETURN false;
 END IF;
 IF e.sessions IS NOT NULL THEN RETURN e.sessions=p_sessions; END IF;
 UPDATE standing.session_effect SET sessions=p_sessions,
  state=CASE WHEN jsonb_array_length(p_sessions)=0 THEN 'completed' ELSE 'captured' END,
  completed_at=CASE WHEN jsonb_array_length(p_sessions)=0 THEN clock_timestamp() END,
  claim_token=CASE WHEN jsonb_array_length(p_sessions)>0 THEN p_claim END,
  claimed_until=CASE WHEN jsonb_array_length(p_sessions)>0 THEN e.claimed_until END
 WHERE event_id=p_event;
 RETURN true;
END $$;

CREATE FUNCTION standing.advance_sessions(p_event uuid,p_claim uuid,p_next integer)
 RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a standing.account%ROWTYPE; e standing.session_effect%ROWTYPE;
BEGIN
 SELECT account.* INTO a FROM standing.account account JOIN standing.session_effect effect
  ON effect.subject_id=account.subject_id WHERE effect.event_id=p_event FOR UPDATE OF account;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO e FROM standing.session_effect WHERE event_id=p_event FOR UPDATE;
 IF p_claim IS NULL OR e.claim_token IS DISTINCT FROM p_claim OR e.claimed_until<=clock_timestamp()
  OR e.state<>'captured' OR a.version<>e.version OR a.status NOT IN('suspended','banned')
  OR p_next IS NULL OR p_next<=e.next_index OR p_next>least(e.next_index+32,jsonb_array_length(e.sessions)) THEN
  RETURN false;
 END IF;
 UPDATE standing.session_effect SET next_index=p_next,failures=0,due_at=clock_timestamp(),
  state=CASE WHEN p_next=jsonb_array_length(e.sessions) THEN 'completed' ELSE 'captured' END,
  completed_at=CASE WHEN p_next=jsonb_array_length(e.sessions) THEN clock_timestamp() END,
  claim_token=NULL,claimed_until=NULL WHERE event_id=p_event;
 RETURN true;
END $$;

CREATE FUNCTION standing.retry_sessions(p_event uuid,p_claim uuid) RETURNS boolean
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 WITH retried AS (
  UPDATE standing.session_effect SET due_at=clock_timestamp()+make_interval(secs=>power(2,least(failures,5))::integer),
   failures=least(failures+1,8),claim_token=NULL,claimed_until=NULL
  WHERE event_id=p_event AND claim_token=p_claim AND claimed_until>clock_timestamp()
   AND state IN('pending','captured') RETURNING 1
 ) SELECT EXISTS(SELECT FROM retried);
$$;

CREATE FUNCTION standing.session_effect_stats() RETURNS TABLE(pending bigint,oldest_seconds double precision)
 LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT count(*),greatest(0,coalesce(extract(epoch FROM clock_timestamp()-min(created_at)),0))::double precision
 FROM standing.session_effect WHERE state IN('pending','captured');
$$;

REVOKE ALL ON standing.session_effect FROM PUBLIC;
REVOKE ALL ON FUNCTION standing.enqueue_sessions(),standing.claim_session_effect(),
 standing.capture_sessions(uuid,uuid,jsonb),standing.advance_sessions(uuid,uuid,integer),
 standing.retry_sessions(uuid,uuid),standing.session_effect_stats() FROM PUBLIC;
GRANT USAGE ON SCHEMA standing TO rac_standing_sessions;
GRANT EXECUTE ON FUNCTION standing.claim_session_effect(),standing.capture_sessions(uuid,uuid,jsonb),
 standing.advance_sessions(uuid,uuid,integer),standing.retry_sessions(uuid,uuid),standing.session_effect_stats()
 TO rac_standing_sessions;
GRANT SELECT ON standing.session_effect TO rac_backup;
