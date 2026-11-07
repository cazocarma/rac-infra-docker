"""P11 reports/cases/actions/appeals boundary in a disposable database. Synthetic data only."""
import json
import uuid

REF = 'audit.reference,audit.reference,audit.reference'
INTAKE = (f'ts.report_submit({REF},text,uuid,audit.reference,text,uuid)', f'ts.appeal_submit({REF},uuid,uuid)')
STAFF = (f'ts.case_queue({REF},integer)', f'ts.case_assign({REF},uuid,audit.reference)', f'ts.case_detail({REF},uuid)',
         f'ts.action_propose({REF},uuid,text,text,text,integer,text)', f'ts.action_approve({REF},uuid)',
         f'ts.action_revoke({REF},uuid,text)', f'ts.appeal_decide({REF},uuid,text)')


def provision(execute, role, functions):
    execute(f"DO $$BEGIN IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role} LOGIN; END IF; END$$;"
            f"DO $$BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO {role}',current_database()); END$$;"
            f"GRANT USAGE ON SCHEMA ts,audit TO {role};"
            + ''.join(f'GRANT EXECUTE ON FUNCTION {f} TO {role};' for f in functions)
            + "DO $$DECLARE c uuid; BEGIN IF NOT EXISTS(SELECT FROM audit.writer_principals WHERE database_role='"
            + role + "') THEN c:=gen_random_uuid(); INSERT INTO audit.chain_heads(chain_id) VALUES(c);"
            " INSERT INTO audit.writer_principals(database_role,actor_id,chain_id) VALUES('"
            + role + "',gen_random_uuid(),c); END IF; END$$;")


def verify(sql, database):
    def execute(statement, role='postgres', ok=True):
        return sql(database, statement, role, ok=ok)

    intake, staff = 'rac_ts_intake_fixture', 'rac_ts_staff_fixture'
    provision(execute, intake, INTAKE)
    provision(execute, staff, STAFF)
    policy = str(uuid.uuid4())
    subject, r1, r2, lead, agent, independent = (str(uuid.uuid4()) for _ in range(6))

    def call(role, function, *args, ok=True):
        rendered = ','.join('NULL' if a is None else (str(a) if isinstance(a, int) else f"'{a}'") for a in args)
        result = execute(f"SELECT ts.{function}(gen_random_uuid(),{rendered});", role, ok)
        return json.loads(result.stdout) if ok else result

    def report(reporter, target, category='drugs', ok=True):
        return call(intake, 'report_submit', reporter, policy, 'listing_revision', target, subject, category, None, ok=ok)

    target = str(uuid.uuid4())
    first = report(r1, target)
    assert first['duplicate'] is False and 'case_id' not in first, 'Reporter learned the case'
    assert report(r1, target) == {**first, 'duplicate': True}, 'Duplicate open report created another'
    assert call(intake, 'report_submit', subject, policy, 'account', subject, subject, 'fraud', None, ok=False).returncode != 0, 'Self report accepted'
    assert call(intake, 'report_submit', subject, policy, 'account', str(uuid.uuid4()), subject, 'fraud', None, ok=False).returncode != 0, 'Self report accepted when resource and realm subject IDs differ'
    assert report(r2, str(uuid.uuid4()), category='unknown', ok=False).returncode != 0, 'Unknown category accepted'
    report(r2, str(uuid.uuid4()))
    report(r2, str(uuid.uuid4()), category='harassment')
    cases = execute(f"SELECT severity||':'||(SELECT count(*) FROM ts.reports r WHERE r.case_id=c.id) FROM ts.cases c WHERE subject='{subject}' ORDER BY severity;").stdout.split()
    assert cases == ['P1:2', 'P2:1'], 'Subject grouping by severity failed: ' + str(cases)
    case = execute(f"SELECT id FROM ts.cases WHERE subject='{subject}' AND severity='P1';").stdout.strip()

    # Conflicts of interest: subject or reporter can neither assign nor be assigned.
    for actor, assignee in ((subject, agent), (lead, subject), (lead, r1), (r2, agent)):
        assert call(staff, 'case_assign', actor, policy, case, assignee, ok=False).returncode != 0, f'Conflicted assignment {actor}->{assignee}'
    queue = call(staff, 'case_queue', lead, policy, 50)
    assert [q['severity'] for q in queue if q['id'] == case] == ['P1'] and all('subject' not in q for q in queue), 'Queue exposed subject'
    assert all(q['id'] != case for q in call(staff, 'case_queue', r1, policy, 50)), 'Reporter saw own reported case'
    assert call(staff, 'case_queue', lead, policy, 51, ok=False).returncode != 0
    call(staff, 'case_assign', lead, policy, case, agent)
    detail = call(staff, 'case_detail', agent, policy, case)
    assert len(detail['reports']) == 2 and all('reporter' not in r for r in detail['reports']), 'Reporter identity exposed'
    assert call(staff, 'case_detail', lead, policy, case, ok=False).returncode != 0, 'Unassigned staff read the case'

    warning = call(staff, 'action_propose', agent, policy, case, 'warning', 'drug_offer', 'actions-fixture-1', None, 'actionWarning')
    assert warning['state'] == 'effective'
    assert call(staff, 'action_propose', lead, policy, case, 'warning', 'drug_offer', 'actions-fixture-1', None, 'actionWarning', ok=False).returncode != 0, 'Unassigned staff acted'
    replay = str(uuid.uuid4())
    restrict = f"SELECT ts.action_propose('{replay}','{agent}','{policy}','{case}','restrict_publish','drug_offer','actions-fixture-1',24,'actionRestrict');"
    restricted = execute(restrict, staff).stdout
    assert restricted == execute(restrict, staff).stdout, 'Retried command created another action'
    assert execute(restrict.replace('restrict_publish', 'restrict_booking'), staff, ok=False).returncode != 0, 'Event reused for another command'
    ban = call(staff, 'action_propose', agent, policy, case, 'ban', 'drug_offer', 'actions-fixture-1', None, 'actionBan')
    assert ban['state'] == 'proposed', 'Ban became effective with one reviewer'
    for approver in (agent, subject, r1):
        assert call(staff, 'action_approve', approver, policy, ban['action_id'], ok=False).returncode != 0, f'{approver} approved without four eyes'
    assert call(staff, 'action_approve', lead, policy, ban['action_id'])['state'] == 'effective'
    assert call(staff, 'action_approve', lead, policy, ban['action_id'])['state'] == 'effective', 'Exact approval replay rejected'
    # Constraints hold even for the schema owner.
    for statement in (f"UPDATE ts.actions SET approved_by=proposed_by WHERE id='{ban['action_id']}';",
                      f"INSERT INTO ts.actions(case_id,subject,kind,reason_code,policy_version,notice_key,proposed_by,state,effective_at) VALUES('{case}','{subject}','ban','x_y','p-1','actionBan','{agent}','effective',now());",
                      f"INSERT INTO ts.actions(case_id,subject,kind,reason_code,policy_version,notice_key,proposed_by,approved_by,state,effective_at) VALUES('{case}','{subject}','ban','x_y','p-1','actionBan','{agent}','{agent}','effective',now());",
                      f"UPDATE ts.actions SET reason_code='other_reason' WHERE id='{warning['action_id']}';",
                      f"DELETE FROM ts.cases WHERE id='{case}';", 'DELETE FROM ts.case_events;'):
        assert execute(statement, ok=False).returncode != 0, 'Case history mutated: ' + statement

    assert call(intake, 'appeal_submit', r1, policy, ban['action_id'], None, ok=False).returncode != 0, 'Non-subject appealed'
    appeal = call(intake, 'appeal_submit', subject, policy, ban['action_id'], None)
    assert call(intake, 'appeal_submit', subject, policy, ban['action_id'], None)['duplicate'] is True, 'Second appeal for one action'
    assert appeal['deadline'].endswith('Z'), 'Appeal response lacks the filing deadline'
    # D07: thirty days to file from the effective time; not a response SLA.
    def age(action, days):
        execute(f"SET session_replication_role=replica; UPDATE ts.actions SET effective_at=effective_at-interval '{days} days' WHERE id='{action}';")
    age(json.loads(restricted)['action_id'], 31)
    late = call(intake, 'appeal_submit', subject, policy, json.loads(restricted)['action_id'], None, ok=False)
    assert late.returncode != 0 and 'appeal_window_closed' in late.stderr, 'Appeal accepted after the thirty-day window'
    age(warning['action_id'], 29)
    assert call(intake, 'appeal_submit', subject, policy, warning['action_id'], None)['duplicate'] is False, 'Appeal inside the window refused'
    age(ban['action_id'], 31)
    replayed = call(intake, 'appeal_submit', subject, policy, ban['action_id'], None)
    assert (replayed['appeal_id'], replayed['duplicate']) == (appeal['appeal_id'], True), 'Timely appeal replay refused after the window'
    for reviewer in (agent, lead, subject, r1):
        assert call(staff, 'appeal_decide', reviewer, policy, appeal['appeal_id'], 'overturned', ok=False).returncode != 0, f'{reviewer} decided a dependent appeal'
    assert call(staff, 'appeal_decide', independent, policy, appeal['appeal_id'], 'overturned')['outcome'] == 'overturned'
    assert call(staff, 'appeal_decide', independent, policy, appeal['appeal_id'], 'upheld', ok=False).returncode != 0, 'Appeal decision rewritten'
    assert call(staff, 'action_revoke', agent, policy, ban['action_id'], 'second_revoke', ok=False).returncode != 0, 'Action revoked twice'
    revoked = call(staff, 'action_revoke', agent, policy, warning['action_id'], 'warning_withdrawn')
    assert revoked['revokes'] == warning['action_id']
    outbox = execute(f"SELECT string_agg(payload->>'kind',',' ORDER BY id) FROM ts.outbox WHERE payload->>'subject'='{subject}';").stdout.strip()
    assert outbox == 'warning,restrict_publish,ban,revocation,revocation', 'Effects not emitted exactly once in order: ' + outbox
    history = execute(f"SELECT count(*) FROM ts.actions WHERE case_id='{case}';").stdout.strip()
    assert history == '5', 'Revocation rewrote instead of appending: ' + history
    audits = execute(f"SELECT string_agg(action||'='||n,',' ORDER BY action) FROM (SELECT action,count(*) n FROM audit.log WHERE case_id='{case}' GROUP BY action) a;").stdout.strip()
    assert audits == 'action.decided=5,appeal.decided=1,case.assigned=1,evidence.accessed=1,report.received=2', 'Audit trail mismatch: ' + audits
    for role in ('rac_user', 'rac_match', 'rac_chat', 'rac_alert', intake):
        assert execute('SELECT count(*) FROM ts.cases;', role, ok=False).returncode != 0, f'{role} read cases'
        assert execute(f"SELECT ts.case_assign(gen_random_uuid(),'{lead}','{policy}','{case}','{independent}');", role, ok=False).returncode != 0, f'{role} assigned a case'
    print('PASS: P11 reports dedup/grouping without revealing cases, conflict-of-interest assignment, assigned-only detail without reporter '
          'identity, four-eyes ban, independent appeal within the thirty-day window, append-only revocation, ordered outbox effects and audit trail', flush=True)
