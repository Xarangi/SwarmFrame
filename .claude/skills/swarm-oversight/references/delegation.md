# Delegating on your own, and leaving a trail

You may fire off sub-agents whenever a bounded question is worth a separate reader. You do not need permission;
you need a reason, and the reason goes in the log.

## When to delegate

- A question is bounded (one scope, one time span, one thing to find out) and would cost you more turns than it
  is worth: "did any of these 9 agents touch host X before 14:00; list event ids".
- Two questions are independent: fire two readers in parallel rather than reading twice yourself.
- The reading needs a view you should not take yourself (raw text): delegate to a role with raw access and treat
  what comes back as a description of untrusted data.
- You are at your span: more reports than you can hold. Delegate the reading; keep the judgement.

## When not to

- To "get a feel" for anything. Read the compressed views.
- To decide. A reader reports; you weigh rivals, grade claims and escalate.
- When an existing reader already covers the scope: re-run it with a sharper task (run_agent) and keep its notes.

## The brief

Four lines: objective (the question, with the scope and span), output shape (counts with bases, event ids, what was
not looked at), boundaries (what not to do: no raw text, no escalation, no spawning), effort (how many calls this
deserves). The Task tool's `description` is recorded as your reason: write the reason there, not "read stuff".

## The trail

Every Task call, spawn, re-run, retirement and escalation is written to the session's delegation log
(`data/runs/<session>/delegations.jsonl`, and the Organization page) with who, what, why and what came back. You
add the lines the system cannot infer with `log_decision`: why you did not delegate something you considered, why
you changed course, what you would have done with more budget. A reviewer should be able to read the log alone and
understand every reader that existed and why.
