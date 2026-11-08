-- P11: timed T&S effects (restrictions, suspensions) expire by time, but the
-- account status is only re-derived when something calls refresh. The effects
-- consumer asks for accounts whose stored status no longer matches their
-- active effects and refreshes each one through refresh_ts_standing.
-- Returns only subject IDs, bounded, in a stable order; nothing else is
-- disclosed and nothing changes here. Once refreshed, an account drops out.
CREATE FUNCTION standing.ts_expiries_due(p_limit int) RETURNS uuid[]
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT COALESCE(array_agg(subject_id ORDER BY subject_id),'{}') FROM (
  SELECT a.subject_id FROM standing.account a
  WHERE EXISTS(SELECT FROM standing.ts_effects e WHERE e.subject_id=a.subject_id
    AND e.kind<>'revocation' AND e.revoked_at IS NULL AND e.ends_at<=clock_timestamp())
   AND a.status<>(SELECT CASE
     WHEN bool_or(e.kind='ban') THEN 'banned'
     WHEN bool_or(e.kind='suspend') THEN 'suspended'
     WHEN bool_or(e.kind IN('restrict_publish','restrict_booking')) THEN 'restricted'
     ELSE 'active' END
    FROM standing.ts_effects e WHERE e.subject_id=a.subject_id AND e.revoked_at IS NULL AND e.kind<>'revocation'
     AND e.starts_at<=clock_timestamp() AND (e.ends_at IS NULL OR e.ends_at>clock_timestamp()))
  ORDER BY a.subject_id
  LIMIT LEAST(GREATEST(COALESCE(p_limit,1),1),100)) due
$$;
REVOKE ALL ON FUNCTION standing.ts_expiries_due(int) FROM PUBLIC;
-- No grant here: the effects consumer login is provisioned explicitly.
