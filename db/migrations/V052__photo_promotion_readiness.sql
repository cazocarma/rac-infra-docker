-- Technical, non-personal capability check. No grants or seed/activation.
CREATE FUNCTION listing_review.photo_promotion_ready(
 p_policy audit.reference,p_listing_policy text,p_pipeline text,p_target audit.reference,
 p_locator audit.digest,p_bucket text,p_region text
) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT listing_review.ready() AND EXISTS(
  SELECT FROM photo.promotion_policies p JOIN photo.promotion_gates g ON g.policy_version=p.policy_version
  JOIN photo.media_targets t ON t.id=p.target_id
  WHERE p.policy_version=p_policy AND p.listing_policy=p_listing_policy AND p.pipeline_version=p_pipeline
   AND p.target_id=p_target AND g.enabled AND encode(t.locator_sha256,'hex')=p_locator
   AND t.bucket_name=p_bucket AND t.region=p_region)
$$;
REVOKE ALL ON FUNCTION listing_review.photo_promotion_ready(audit.reference,text,text,audit.reference,audit.digest,text,text) FROM PUBLIC;
