-- Own history uses a bounded descending keyset, including timestamp ties.
CREATE INDEX document_acceptances_history ON public.document_acceptances(user_id,accepted_at DESC,document_id DESC);
