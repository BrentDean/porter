# Training corpus and inference confirmation

Porter treats deterministic recognition coverage as a curated product surface rather than allowing unmatched text to become executable behavior automatically.

## Training capture

The CLI command `training` enters a non-executing capture mode. Every line is stored as a raw training example until `END` is entered. Training text never reaches the request dispatcher, tools, actions, or inference providers.

Intentional training examples are stored separately from normal unmatched requests so review can distinguish seeded examples from production usage gaps.

## Group-first training review

The CLI command `training review` groups natural-language variants by meaning instead of requiring a reviewer to classify each phrase separately or remember internal Porter intent names.

The reviewer selects one or more example IDs, for example `2-5,7`, gives the group a plain-English description, and chooses how Porter should eventually handle that group:

- an existing Porter behavior;
- a new deterministic behavior;
- AI / inference;
- discard.

For an existing behavior, Porter displays the currently available deterministic behaviors as a numbered, human-readable list and stores the internal target label itself. The reviewer never needs to memorize labels such as `PorterDiskUsage`.

For a new deterministic behavior, no internal intent label is required. Porter records the grouped examples and their plain-English meaning as a candidate capability. An internal intent name can be assigned later when that behavior is actually implemented.

Grouping does not execute any example and does not promote it into Porter's runtime vocabulary. Multiple wording variants may belong to one group and later become one deterministic intent or behavior.

Training examples captured before grouping was introduced remain eligible for grouping after migrations 010 and 011. The migrations add review and grouping metadata without replacing or recapturing the original raw examples.

`training groups` lists the groups that have been created.

## Inference confirmation

After deterministic intents and deterministic tools decline a normal CLI request, Porter asks for explicit confirmation before local inference. Pressing Enter authorizes local AI for that request; `n` or `no` declines it.

The dispatcher owns the inference-authorization boundary but not interactive input. The CLI supplies the authorization callback, allowing future surfaces such as a web UI to represent the same boundary with an explicit button rather than terminal input.

## Recognition gaps

Every request that reaches the inference confirmation boundary is recorded locally as a recognition gap. Porter groups normalized wording and tracks total occurrences plus AI-approved and AI-declined counts. This provides evidence for later deterministic vocabulary work without automatically changing executable behavior.

Intentional training examples and recognition gaps are both local SQLite data. Neither source automatically creates an intent, tool, action, or permission.

## Promotion workflow

The intended workflow is:

1. capture natural phrases through `training` and normal recognition gaps;
2. group intentional examples by meaning with `training review`;
3. map groups to an existing behavior or mark them as candidate new deterministic behavior, inference, or discard;
4. inspect recognition gaps for recurring unmet requests;
5. assign internal intent identifiers only when needed for implementation;
6. promote reviewed deterministic language into version-controlled intent data;
7. add routing evaluations/tests;
8. merge through the normal CI workflow.

This preserves auditability and keeps side-effecting behavior behind reviewed code and deterministic intent definitions.
