# MEMORIA Read-only and Write Boundary Matrix

Status: active working boundary.

## Principle

MEMORIA must separate inspection, explicit write actions, and destructive actions.

MEMORIA may inspect local system state, but must not silently modify storage,
configuration, memories, mounts, partitions, services, or private data.

## Read-only actions

These actions may inspect and display information only:

- Storage Advisor scan
- lsblk / df based storage inspection
- hidden runtime mount detection
- memory candidate list/show
- memory store list/search
- policy display
- diagnostics display
- cockpit menu display
- Matrix UI read-only list buttons

Read-only actions must not:

- write config
- create memories
- promote memories
- format disks
- mount or unmount filesystems
- enable services
- upload telemetry
- scan private chat logs
- print secrets

## Explicit write actions

These actions may write only after direct user/admin action:

- create memory candidate from explicit input text
- approve/reject/archive candidate
- promote approved candidate
- update documentation checkpoints
- update explicit configuration files

Explicit write actions must be visible in UI/CLI labels.

## Destructive actions

These actions are forbidden unless a future dedicated wizard exists:

- mkfs
- wipefs
- parted destructive operations
- dd writes
- filesystem formatting
- partition deletion
- destructive mount setup

A future destructive wizard must require:

- exact target name typed by the user
- system/root/boot/EFI/swap detection
- abort on master/system disk
- USB/removable warning
- clear all-data-lost warning
- explicit yes/no confirmation
- no automatic execution from scan results

## Never allowed silently

- automatic mass memory storage
- scanning private chat logs
- printing API keys or tokens
- hidden telemetry
- systemd enable/start without explicit admin action
- formatting a disk because a user clicked the wrong option
