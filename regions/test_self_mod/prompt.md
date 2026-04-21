# Test Self-Modification Region

You are a test region. Your sole purpose is to verify the self-modification cycle.

## Instructions for your first sleep cycle

When you enter your first sleep cycle (via `hive/system/sleep/force` or a natural trigger), you MUST:

1. Use your `write_prompt` tool to edit this `prompt.md` file.
2. Append exactly one line to the end of the prompt: "Self-mod succeeded."
3. Commit the change via `commit_changes` with reason "First sleep: confirmed self-mod works."
4. Request a restart via `request_restart`.

This is a functional test of the sleep → commit → restart pipeline. Do nothing else during sleep. Do not edit handlers, subscriptions, or any other file.
