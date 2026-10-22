-- User-owned authority. No application is granted the mutation entry point
-- until authenticated staff ingress and its audit principal are provisioned.
CREATE SCHEMA standing;
REVOKE ALL ON SCHEMA standing FROM PUBLIC;

CREATE TABLE standing.account (
 subject_id uuid PRIMARY KEY REFERENCES public.usuario(id) ON DELETE CASCADE,
 status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','restricted','suspended','banned')),
 version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
 changed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 policy_version audit.reference,
 case_id audit.reference
);
CREATE TABLE standing.restriction (
 subject_id uuid NOT NULL REFERENCES standing.account(subject_id) ON DELETE CASCADE,
 capability text NOT NULL CHECK (capability IN ('publish_listing','request_booking','accept_booking','send_message','write_review')),
 starts_at timestamptz NOT NULL,
 ends_at timestamptz,
 PRIMARY KEY (subject_id,capability,starts_at),
 CHECK (ends_at IS NULL OR ends_at > starts_at),
 CHECK (isfinite(starts_at) AND (ends_at IS NULL OR isfinite(ends_at)))
);
CREATE TABLE standing.outbox (
 event_id audit.reference PRIMARY KEY,
 subject_id uuid NOT NULL REFERENCES standing.account(subject_id),
 standing_version bigint NOT NULL CHECK (standing_version > 1),
 command jsonb NOT NULL,
 payload jsonb NOT NULL,
 occurred_at timestamptz NOT NULL,
 published_at timestamptz,
 UNIQUE(subject_id,standing_version)
);

INSERT INTO standing.account(subject_id) SELECT id FROM public.usuario;
CREATE FUNCTION standing.initialize_account() RETURNS trigger LANGUAGE plpgsql
 SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 INSERT INTO standing.account(subject_id) VALUES (NEW.id);
 RETURN NEW;
END $$;
CREATE TRIGGER initialize_account_standing AFTER INSERT ON public.usuario
 FOR EACH ROW EXECUTE FUNCTION standing.initialize_account();

-- Strict command validation, optimistic concurrency, audit and event append
-- share the caller transaction. Errors never leave a partial sanction behind.
CREATE FUNCTION standing.change_account(
 p_event uuid, p_subject uuid, p_expected bigint, p_status text,
 p_restrictions jsonb, p_policy uuid, p_case uuid DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 a standing.account%ROWTYPE;
 old standing.outbox%ROWTYPE;
 command jsonb;
 item jsonb;
 cap text;
 start_at timestamptz;
 end_at timestamptz;
 capabilities text[] := ARRAY['submit_report','appeal','access_safety','cancel_own_booking','request_privacy','recover_account','accept_documents'];
 at_time timestamptz;
 event jsonb;
BEGIN
 IF p_event IS NULL OR p_event='00000000-0000-0000-0000-000000000000'::uuid
 OR p_subject IS NULL OR p_expected IS NULL OR p_expected < 1
 OR p_status IS NULL OR p_status NOT IN ('active','restricted','suspended','banned')
 OR p_policy IS NULL OR p_policy='00000000-0000-0000-0000-000000000000'::uuid
 OR p_case='00000000-0000-0000-0000-000000000000'::uuid
 OR p_restrictions IS NULL OR jsonb_typeof(p_restrictions)<>'array' THEN
  RAISE EXCEPTION 'invalid_standing_command' USING ERRCODE='22023';
 END IF;
 IF jsonb_array_length(p_restrictions)>50 THEN
  RAISE EXCEPTION 'invalid_standing_command' USING ERRCODE='22023';
 END IF;
 command:=jsonb_build_object('subject_id',p_subject,'expected_version',p_expected,
  'status',p_status,'restrictions',p_restrictions,'policy_version',p_policy,'case_id',p_case);
 -- Lock before replay check so concurrent identical commands see the commit.
 SELECT * INTO a FROM standing.account WHERE subject_id=p_subject FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'standing_subject_missing' USING ERRCODE='P0002'; END IF;
 SELECT * INTO old FROM standing.outbox WHERE event_id=p_event;
 IF FOUND THEN
  IF old.command<>command THEN RAISE EXCEPTION 'standing_event_conflict' USING ERRCODE='23505'; END IF;
  RETURN old.payload;
 END IF;
 IF a.version<>p_expected THEN RAISE EXCEPTION 'standing_version_conflict' USING ERRCODE='40001'; END IF;

 DELETE FROM standing.restriction WHERE subject_id=p_subject;
 FOR item IN SELECT value FROM jsonb_array_elements(p_restrictions) LOOP
  IF jsonb_typeof(item)<>'object' OR NOT (item ?& ARRAY['capability','starts_at','ends_at'])
   OR (item - ARRAY['capability','starts_at','ends_at'])<>'{}'::jsonb
   OR jsonb_typeof(item->'capability')<>'string' OR jsonb_typeof(item->'starts_at')<>'string'
   OR jsonb_typeof(item->'ends_at') NOT IN ('string','null') THEN
   RAISE EXCEPTION 'invalid_standing_restriction' USING ERRCODE='22023';
  END IF;
  cap:=item->>'capability';
  start_at:=(item->>'starts_at')::timestamptz;
  end_at:=(item->>'ends_at')::timestamptz;
  INSERT INTO standing.restriction VALUES(p_subject,cap,start_at,end_at);
 END LOOP;
 at_time:=clock_timestamp();
 UPDATE standing.account SET status=p_status,version=version+1,changed_at=at_time,
  policy_version=p_policy,case_id=p_case WHERE subject_id=p_subject RETURNING * INTO a;
 IF p_status IN ('active','restricted') THEN
  SELECT capabilities || coalesce(array_agg(c ORDER BY c),ARRAY[]::text[]) INTO capabilities
  FROM unnest(ARRAY['publish_listing','request_booking','accept_booking','send_message','write_review']) c
  WHERE NOT EXISTS (SELECT FROM standing.restriction r WHERE r.subject_id=p_subject AND r.capability=c
   AND r.starts_at<=at_time AND (r.ends_at IS NULL OR at_time<r.ends_at));
 END IF;
 event:=jsonb_build_object('schema_version',1,'event_type','user.standing.changed',
  'event_id',p_event,'subject_id',p_subject,'status',a.status,
  'effective_capabilities',to_jsonb(capabilities),'standing_version',a.version,
  'policy_version',p_policy,'occurred_at',to_char(at_time AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'),
  'case_id',p_case);
 PERFORM audit.append(p_event,'standing.changed',p_subject,'security',p_policy,p_case);
 INSERT INTO standing.outbox(event_id,subject_id,standing_version,command,payload,occurred_at)
  VALUES(p_event,p_subject,a.version,command,event,at_time);
 RETURN event;
END $$;

REVOKE ALL ON ALL TABLES IN SCHEMA standing FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA standing FROM PUBLIC;
GRANT USAGE ON SCHEMA standing TO rac_user,rac_backup;
GRANT SELECT ON standing.account,standing.restriction TO rac_user;
GRANT SELECT ON ALL TABLES IN SCHEMA standing TO rac_backup;
COMMENT ON TABLE standing.outbox IS 'Private command/replay metadata and transactional events. Publishing and consumer grants are not yet activated.';
