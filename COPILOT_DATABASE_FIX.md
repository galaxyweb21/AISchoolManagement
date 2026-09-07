# Copilot PostgreSQL UUID Repair

## Problem fixed

The Render PostgreSQL database can contain an `ai_engine_aimessage.conversation_id`
column stored as `BIGINT` while the application uses UUID conversation IDs.

This causes the main Copilot page to fail while Django prefetches messages:

`operator does not exist: bigint = uuid`

## Fix

Migration `ai_engine.0007_repair_aimessage_conversation_uuid` drops and recreates
`AIMessage` with the UUID schema used by the current Django model.

The migration intentionally discards old Copilot message rows because a legacy
BIGINT conversation reference cannot be reliably mapped to the UUID conversation
rows. Copilot conversations and all other school/application data are untouched.

## Deployment

No manual SQL is required. The existing deployment entrypoint runs Django
migrations before starting the application, so deploying this release applies
migration 0007 automatically.

After deployment, open:

`/ai-engine/copilot/`

and create a new Copilot conversation. The Ghana Education Copilot is not
changed by this repair.
