# MEMORIA Memory Storage Switching

Status: accepted  
Scope: Memory storage, retrieval, intake, candidates, promotion, migration

## Principle

MEMORIA memory paths must not be hardcoded to the project directory after a user selects an external or dedicated memory storage root.

A user may move MEMORIA memory storage to a new SSD, HDD, USB device, or another mounted filesystem.

MEMORIA components must resolve memory paths through the Memory Storage Manager or the shared storage path helper.

## Path Resolution Order

MEMORIA path resolution follows this order:

1. Explicit environment override, if set.
2. Memory Storage Manager selected root.
3. Project-local fallback path.

This allows:

- normal users to use the selected storage root
- admins/tests to override paths with environment variables
- development fallback when no external storage has been selected

## Required Behavior

Components that read or write memory-related data must not assume:

- `knowledge/memory`
- `knowledge/memory_candidates`
- `/root/memoria/knowledge`
- any fixed local project path

They must use managed paths for:

- durable memory
- memory candidates
- duplicate checks
- promotion
- retrieval
- import/intake processing

## Storage Switching Safety

When switching storage, MEMORIA must:

- not format disks automatically
- not delete source memory files before checksum/manifest verification
- not scan private directories automatically
- not expose secrets or API keys
- warn about removable/USB storage risks
- support freeze/stop modes during migration
- restore runtime mode after migration
- keep source files unless deletion is explicitly confirmed

## User Guidance

Recommended flow:

1. Mount the new storage device.
2. Verify filesystem and free space.
3. Select the MEMORIA storage root with Memory Storage Manager.
4. Freeze writes during migration.
5. Copy memory data.
6. Compare manifests/checksums.
7. Only then allow explicit source cleanup.
8. Run retrieval and memory live tests.
9. Document the switch.

## Non-negotiable Rule

If a user selects a new memory storage root, MEMORIA readers and writers must follow that selected root.

A memory that exists on the selected storage root must be retrievable without requiring manual path edits.
