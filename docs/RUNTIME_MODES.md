# MEMORIA Runtime Modes

Status: active working design.

## Modes

### NORMAL

MEMORIA operates normally.

Allowed:
- retrieval from approved durable memory
- candidate creation from explicit input
- explicit candidate approval/rejection/archive
- explicit promotion of approved candidates
- controlled background processing if configured

### THINKING_MODE

MEMORIA thinks with existing approved knowledge only.

Allowed:
- retrieval from approved durable memory
- answering based on existing knowledge

Blocked:
- new memory candidates
- durable memory writes
- promotion
- auto policy writes
- background intake

Meaning:

> I only think with what I already know. I store nothing new.

### SERVICE_STOP

MEMORIA processing is stopped or paused.

Blocked:
- retrieval processing
- memory intake
- candidate creation
- promotion
- durable writes
- background workers

Meaning:

> MEMORIA service-level processing is stopped. No new processing or writes.

## Naming decision

The mode is named SERVICE_STOP instead of RUN_STOP because RUN STOP can be confused
with ordinary start/stop UI controls. SERVICE_STOP is a runtime safety state.

## Safety rule

Runtime modes must preserve User Sovereignty:

- no hidden storage
- no automatic mass memory creation
- no private chat log scanning
- no secret printing
- no destructive system action
