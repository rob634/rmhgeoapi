#!/usr/bin/env python3
"""
Update all Python file headers with EPOCH markers.

This script adds EPOCH status to files based on the audit in EPOCH_FILE_AUDIT.md
"""

import re
from pathlib import Path

# File categorizations from EPOCH_FILE_AUDIT.md
EPOCH4_ACTIVE = [
    # Root
    'test_core_machine.py',
    'test_deployment_ready.py',
    # Core
    'core/machine.py',
    'core/models/stage.py',
    # Jobs (all files)
    'jobs/__init__.py',
    'jobs/workflow.py',
    'jobs/registry.py',
    'jobs/hello_world.py',
    # Services (Epoch 4 only)
    'services/__init__.py',
    'services/task.py',
    'services/registry.py',
    'services/hello_world.py',
]

EPOCH3_DEPRECATED = [
    'controller_base.py',
    'controller_container.py',
    'controller_hello_world.py',
    'controller_service_bus.py',
    'controller_service_bus_container.py',
    'controller_service_bus_hello.py',
    'controller_stac_setup.py',
    'debug_service_bus.py',
]

SHARED_BOTH_EPOCHS = [
    'config.py',
    'controller_factories.py',
    'exceptions.py',
    'function_app.py',
    'registration.py',
    'schema_base.py',
    'schema_blob.py',
    'schema_manager.py',
    'schema_orchestration.py',
    'schema_queue.py',
    'schema_sql_generator.py',
    'schema_updates.py',
    'schema_workflow.py',
    'service_bus_list_processor.py',
    'task_factory.py',
    'util_logger.py',
    # Services shared
    'services/service_blob.py',
    'services/service_hello_world.py',
    'services/service_stac_setup.py',
]

INFRASTRUCTURE = [
    # Core (most files)
    'core/__init__.py',
    'core/core_controller.py',
    'core/state_manager.py',
    'core/orchestration_manager.py',
    'core/logic/__init__.py',
    'core/logic/calculations.py',
    'core/logic/transitions.py',
    'core/models/__init__.py',
    'core/models/context.py',
    'core/models/enums.py',
    'core/models/job.py',
    'core/models/results.py',
    'core/models/task.py',
    'core/schema/__init__.py',
    'core/schema/deployer.py',
    'core/schema/orchestration.py',
    'core/schema/queue.py',
    'core/schema/sql_generator.py',
    'core/schema/updates.py',
    'core/schema/workflow.py',
    # Infrastructure (all files)
    'infrastructure/__init__.py',
    'infrastructure/base.py',
    'infrastructure/blob.py',
    'infrastructure/factory.py',
    'infrastructure/interface_repository.py',
    'infrastructure/jobs_tasks.py',
    'infrastructure/postgresql.py',
    'infrastructure/queue.py',
    'infrastructure/service_bus.py',
    'infrastructure/vault.py',
    # Triggers (all files)
    'triggers/__init__.py',
    'triggers/db_query.py',
    'triggers/get_job_status.py',
    'triggers/health.py',
    'triggers/http_base.py',
    'triggers/poison_monitor.py',
    'triggers/schema_pydantic_deploy.py',
    'triggers/submit_job.py',
    # Utils (all files)
    'utils/__init__.py',
    'utils/contract_validator.py',
    'utils/import_validator.py',
]


def add_epoch_marker(filepath: Path, marker: str) -> bool:
    """Add EPOCH marker to file header if not already present."""
    try:
        content = filepath.read_text()

        # Check if already has EPOCH marker
        if '# EPOCH:' in content:
            print(f"  ⏭️  Skipped (already marked): {filepath}")
            return False

        # Find the header section
        # Look for pattern: # ============================================================================
        # Then add marker after it
        header_pattern = r'(# ={70,}\n# CLAUDE CONTEXT[^\n]*\n# ={70,}\n)'

        match = re.search(header_pattern, content)
        if not match:
            print(f"  ⚠️  No header found: {filepath}")
            return False

        # Insert marker after the header divider
        header_end = match.end()
        new_content = (
            content[:header_end] +
            marker + '\n' +
            content[header_end:]
        )

        filepath.write_text(new_content)
        print(f"  ✅ Updated: {filepath}")
        return True

    except Exception as e:
        print(f"  ❌ Error updating {filepath}: {e}")
        return False


def main():
    print('=' * 70)
    print('UPDATING EPOCH MARKERS IN PYTHON FILES')
    print('=' * 70)
    print()

    base_dir = Path('.')

    # Update Epoch 4 Active files
    print('🟢 EPOCH 4 - ACTIVE (13 files)')
    marker = '# EPOCH: 4 - ACTIVE ✅\n# STATUS: Core component of new architecture'
    for filepath in EPOCH4_ACTIVE:
        path = base_dir / filepath
        if path.exists():
            add_epoch_marker(path, marker)
    print()

    # Update Epoch 3 Deprecated files
    print('🔴 EPOCH 3 - DEPRECATED (8 files)')
    marker = ('# EPOCH: 3 - DEPRECATED ⚠️\n'
              '# STATUS: Replaced by Epoch 4 CoreMachine\n'
              '# MIGRATION: Will be archived after Storage Queue triggers migrated')
    for filepath in EPOCH3_DEPRECATED:
        path = base_dir / filepath
        if path.exists():
            add_epoch_marker(path, marker)
    print()

    # Update Shared files
    print('🟡 SHARED - USED BY BOTH (17 files)')
    marker = ('# EPOCH: SHARED - BOTH EPOCHS\n'
              '# STATUS: Used by Epoch 3 and Epoch 4\n'
              '# NOTE: Careful migration required')
    for filepath in SHARED_BOTH_EPOCHS:
        path = base_dir / filepath
        if path.exists():
            add_epoch_marker(path, marker)
    print()

    # Update Infrastructure files
    print('🔵 INFRASTRUCTURE - ALWAYS ACTIVE (38 files)')
    marker = ('# EPOCH: INFRASTRUCTURE\n'
              '# STATUS: Core infrastructure - shared by all epochs')
    for filepath in INFRASTRUCTURE:
        path = base_dir / filepath
        if path.exists():
            add_epoch_marker(path, marker)
    print()

    print('=' * 70)
    print('EPOCH MARKER UPDATE COMPLETE')
    print('=' * 70)


if __name__ == '__main__':
    main()
