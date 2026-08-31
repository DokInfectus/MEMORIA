# MEMORIA Runtime and Service Architecture

Status: accepted  
Scope: runtime modes, background services, cockpit, Matrix UI, source/input services

## Problem

Runtime Mode is not only a label. Runtime Mode also controls enabled MEMORIA background services.

MEMORIA must not become a loose collection of tools that users have to start manually.

If a user activates NORMAL mode, enabled MEMORIA services should run in the background.
If a user activates SERVICE_STOP, MEMORIA processing services should stop.

The user should not have to start many separate watchers by hand.

## Architecture Roles

### Core Tools

Core tools implement one clear function.

Examples:

- memory store
- candidate store
- memory intake
- file import
- source ledger
- prompt engine
- adapters

Core tools must be callable from Cockpit, Matrix UI and tests.

### Runtime / Service Layer

Runtime / Service Mode controls background MEMORIA processing.

It owns:

- service status
- starting enabled services
- stopping running services
- applying runtime mode transitions

### Cockpit

The Terminal Cockpit is the headless admin interface.

It may expose read/write actions, but long-running processes must not block the Cockpit.

Cockpit must call Core Tools or Service Manager commands.

### Matrix UI

Matrix UI is optional and user-friendly.

It must use the same Core Tools and Service Manager logic as the Cockpit.
It must not duplicate core behavior.

## Runtime Modes

### NORMAL

NORMAL means normal MEMORIA operation.

When NORMAL is activated:

- runtime mode is set to NORMAL
- enabled background services may be started
- disabled services remain stopped
- status must show which services are running, stopped or disabled

### THINKING_MODE

THINKING_MODE allows read/retrieval behavior while blocking new memory writes.

When THINKING_MODE is activated:

- retrieval may remain available
- candidate creation is blocked by Runtime Guard
- promotion and durable writes are blocked
- write-producing services should be paused or stopped unless explicitly read-only

### SERVICE_STOP

SERVICE_STOP pauses MEMORIA processing.

When SERVICE_STOP is activated:

- runtime mode is set to SERVICE_STOP
- background services are stopped
- candidate creation is blocked
- promotion and durable writes are blocked

## Source Ledger Placement

The Source Ledger has two parts:

### Source Ledger Scan

A one-shot read/record action.

Belongs in:

- Memory / Gedanken Speicherung
- Matrix UI Memory area

It may:

- scan the explicit import inbox
- record new source events in the daily ledger

It must not:

- create candidates
- write durable memory
- scan private directories

### Source Ledger Watch

A long-running background watcher.

Belongs in:

- Runtime / Service Mode
- Service Manager

It must not be a blocking Memory menu action.

## Service Manager Requirement

MEMORIA needs a service control layer before more background watchers are added.

The service control layer should provide:

- status
- start service
- stop service
- start enabled services
- stop all services
- apply runtime mode

Initial service:

- source_ledger_watch

Future services may include:

- import_processor
- openwebui_inlet
- bridge_service

## UI Rule

No functionality should be implemented separately three times.

Correct flow:

1. Core Tool implements behavior.
2. Service Manager controls background lifecycle if needed.
3. Cockpit calls Core Tool or Service Manager.
4. Matrix UI calls the same Core Tool or Service Manager.

## Non-Negotiable Safety

- No hidden telemetry.
- No private directory scans.
- No automatic durable memory by default.
- No token/API key output.
- No blocking watcher in Memory menu.
- No service autostart unless explicitly configured.
- SERVICE_STOP must stop MEMORIA background processing services.
