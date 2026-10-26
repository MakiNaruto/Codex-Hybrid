# Usage and verification

**English** · [简体中文](../zh-CN/usage.md)

[Project home](../../README.md) · [Documentation](README.md)

## Test a model connection

Open the management page, save and enable a model, then click **Test connection**. The test sends `Reply with exactly hello and nothing else.` with an output budget of at most 8192 tokens, or the model's lower configured limit.

Success means this basic request completed. Full Codex sessions and tool calls need separate verification. The 8192-token limit is an output budget, not a guarantee of total usage or cost.

## Use a third-party model in a main chat

Select a configured model in Codex's native model picker, start a new chat, and send:

```text
Reply only: Hello World
```

Expected reply: `Hello World`. A new chat helps verify the model selection. Full sessions include system instructions, tool definitions, and history, so their input is usually larger than a management-page connection test.

## Have an official-model agent create a third-party subagent

Select an official model that supports native subagents in the main chat, then send the prompt below. **Replace the model key first.** The manual YAML example uses `deepseek/flash`; the setup wizard uses `custom/default`. For CC Switch, use the actual registered key. Run `status` to list model keys.

```text
Create a native subagent with model deepseek/flash, fork_turns none,
and reasoning_effort low, if supported by that model.
Subtask: reply only CHILD_OK and do not call tools.
First state which model you will use, then create the subagent, wait for it,
and relay its result. Do not answer the subtask yourself or substitute an
MCP or command-line call for the native subagent.
```

Expected sequence: the main agent names the model → native subagent activity appears → the subagent replies `CHILD_OK` → the main agent relays the result. The client must expose and allow native subagent tools; a prompt cannot enable unavailable tools.

Verify routing using the model information in native subagent activity and gateway logs. A model's own identity claim is insufficient.

<details>
<summary>Verification scope</summary>

The replies above are expected examples. Verify the subagent workflow in your own desktop session; the connection test described earlier only covers a basic request.

</details>

## Daily management

See [common commands](../../README.md#common-commands) for starting, stopping, and checking the service. Commands use the fixed user directory; custom directories must be supplied explicitly. See [CLI defaults](cli.md#instance-configuration) for precedence and [data directory](configuration.md#data-directory) for migration.

After running `refresh-models`, restart the service and fully quit and reopen Codex. After adding or removing models, update the client catalog and restart Codex. API key or base URL updates take effect on the next request.

See [configuration](configuration.md) and [commands](cli.md) for more detail.
