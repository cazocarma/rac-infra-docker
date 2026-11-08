-- P11 customer intake. The reporter comes from the authenticated token; the
-- reported subject never comes from the caller. The owner of each target
-- resolves it from its own data (ADR-003 owner snapshot). This increment
-- covers targets owned by user: a public compa profile ("account", by
-- compa_perfil.id) and a published listing revision. Other target types stay
-- refused until their owners (match, chat) provide a resolver.

-- User-owned resolver: the realm principal behind a reportable target, or
-- NULL. Missing, unpublished and unsupported targets look the same.
CREATE FUNCTION public.ts_report_subject(p_type text,p_id uuid) RETURNS uuid
 LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE principal text;
BEGIN
 IF p_type='account' THEN
  SELECT u.keycloak_id INTO principal FROM public.compa_perfil cp JOIN public.usuario u ON u.id=cp.usuario_id
  WHERE cp.id=p_id;
 ELSIF p_type='listing_revision' THEN
  SELECT u.keycloak_id INTO principal FROM public.listings l
  JOIN public.compa_perfil cp ON cp.id=l.compa_id JOIN public.usuario u ON u.id=cp.usuario_id
  WHERE l.published_revision_id=p_id AND l.state='published';
 ELSE
  RETURN NULL;
 END IF;
 IF principal IS NULL OR principal !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' THEN
  RETURN NULL;  -- Only canonical realm principals; never an internal ID.
 END IF;
 RETURN principal::uuid;
END $$;
REVOKE ALL ON FUNCTION public.ts_report_subject(text,uuid) FROM PUBLIC;

-- At most this many reports per reporter per rolling day. Duplicates of an
-- open report are grouped and never count against the reporter (D06).
CREATE FUNCTION ts.report_daily_limit() RETURNS int
 LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$ SELECT 20 $$;
REVOKE ALL ON FUNCTION ts.report_daily_limit() FROM PUBLIC;

CREATE FUNCTION ts.report_receive(p_event audit.reference,p_reporter audit.reference,p_policy audit.reference,
 p_target_type text,p_target uuid,p_category text)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE subject uuid;
BEGIN
 IF p_event IS NULL OR p_reporter IS NULL OR p_policy IS NULL OR p_target IS NULL
  OR p_target_type IS NULL OR ts.severity(p_category) IS NULL THEN
  RAISE EXCEPTION 'invalid_report' USING ERRCODE='22023';
 END IF;
 subject:=public.ts_report_subject(p_target_type,p_target);
 IF subject IS NULL THEN
  RAISE EXCEPTION 'report_target_unavailable' USING ERRCODE='P0002';
 END IF;
 -- An open report for the same target is returned unchanged by report_submit;
 -- only new reports count toward the reporter's daily limit.
 PERFORM pg_advisory_xact_lock(hashtextextended('report-reporter:'||p_reporter::text,0));
 IF NOT EXISTS(SELECT FROM ts.reports WHERE reporter=p_reporter AND target_type=p_target_type AND target_id=p_target AND state='open')
  AND (SELECT count(*) FROM ts.reports WHERE reporter=p_reporter AND received_at>clock_timestamp()-interval '1 day')>=ts.report_daily_limit() THEN
  RAISE EXCEPTION 'report_rate_limited' USING ERRCODE='54000';
 END IF;
 RETURN ts.report_submit(p_event,p_reporter,p_policy,p_target_type,p_target,subject,p_category,NULL);
END $$;
REVOKE ALL ON FUNCTION ts.report_receive(audit.reference,audit.reference,audit.reference,text,uuid,text) FROM PUBLIC;
