# Record every step that worked

`ms_reduction_log` may be a deferred tool: load its schema before the first
call. It is granted wherever this file is named.

After each step you have **validated** — the script ran, the caltable or MS
came out as expected, the diagnostic looked right — append it to the
reduction ledger:

```
ms_reduction_log(action='append', workdir=<workdir>, tool=<tool name>,
                 params=<the exact params that worked>,
                 script_path=<the script you ran>,
                 outputs=<paths and key numbers worth keeping>,
                 rationale=<why, in one line>,
                 skill_rule=<the file and step you followed, e.g. '07 Step 3'>)
```

Append the call that worked, not the one you meant to make, and only after
its output has been checked. One entry per write call:

- `tool` is the write tool's own name (`ms_gaincal`, not `ms_gaincal (G0)`);
  three `ms_applycal` calls are three entries. Use `manual` for work done off
  the tools.
- `params` are the literal arguments of that call; `execute` is `true` or
  `false`, as passed.
- `script_path` is the script that actually ran: the generated one, the
  generated one after your edit, or your own (`manual`). Required unless the
  call ran with `execute=true`; always required for `manual`. The ledger stores its hash; replay
  runs it.
- Checks (`ms_calsol_stats`, `ms_flag_summary`, ...) are not entries. Put
  their key numbers in the `outputs` of the step they verify.

The tool refuses an entry it could not replay and says why. The ledger is the working record of this
reduction: `action='list'` gives a compact step summary when you have lost
the thread, and `action='render'` emits the ordered recipe plus a replay
script, which is what makes the reduction reproducible by someone else (or
by you, six months later). A step that is not appended did not happen as far
as the record is concerned.

