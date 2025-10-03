#!/usr/bin/env python3
"""
Update headers from vague "INFRASTRUCTURE" to descriptive categories.
"""

import re
from pathlib import Path

# New descriptive categories
CATEGORIES = {
    # Data Models - Database Entities
    'DATA_MODELS': {
        'files': [
            'core/models/__init__.py',
            'core/models/context.py',
            'core/models/enums.py',
            'core/models/job.py',
            'core/models/task.py',
            'core/models/results.py',
        ],
        'marker': ('# CATEGORY: DATA MODELS - DATABASE ENTITIES\n'
                   '# PURPOSE: Pydantic model mapping to PostgreSQL table/database structure\n'
                   '# EPOCH: Shared by all epochs (database schema)')
    },

    # Schemas - Validation & Transformation
    'SCHEMAS': {
        'files': [
            'core/schema/__init__.py',
            'core/schema/deployer.py',
            'core/schema/orchestration.py',
            'core/schema/queue.py',
            'core/schema/sql_generator.py',
            'core/schema/updates.py',
            'core/schema/workflow.py',
        ],
        'marker': ('# CATEGORY: SCHEMAS - DATA VALIDATION & TRANSFORMATION\n'
                   '# PURPOSE: Pydantic models for validation, serialization, and data flow\n'
                   '# EPOCH: Shared by all epochs (not persisted to database)')
    },

    # Azure Resource Repositories
    'REPOSITORIES': {
        'files': [
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
        ],
        'marker': ('# CATEGORY: AZURE RESOURCE REPOSITORIES\n'
                   '# PURPOSE: Azure SDK wrapper providing data access abstraction\n'
                   '# EPOCH: Shared by all epochs (infrastructure layer)')
    },

    # State Management & Orchestration
    'STATE_MGMT': {
        'files': [
            'core/__init__.py',
            'core/state_manager.py',
            'core/orchestration_manager.py',
            'core/core_controller.py',
        ],
        'marker': ('# CATEGORY: STATE MANAGEMENT & ORCHESTRATION\n'
                   '# PURPOSE: Core architectural component for job/task lifecycle management\n'
                   '# EPOCH: Shared by all epochs (may evolve with architecture changes)')
    },

    # Business Logic Helpers
    'LOGIC': {
        'files': [
            'core/logic/__init__.py',
            'core/logic/calculations.py',
            'core/logic/transitions.py',
        ],
        'marker': ('# CATEGORY: BUSINESS LOGIC HELPERS\n'
                   '# PURPOSE: Shared utility functions for calculations and state transitions\n'
                   '# EPOCH: Shared by all epochs (business logic)')
    },

    # HTTP Trigger Endpoints
    'TRIGGERS': {
        'files': [
            'triggers/__init__.py',
            'triggers/db_query.py',
            'triggers/get_job_status.py',
            'triggers/health.py',
            'triggers/http_base.py',
            'triggers/poison_monitor.py',
            'triggers/schema_pydantic_deploy.py',
            'triggers/submit_job.py',
        ],
        'marker': ('# CATEGORY: HTTP TRIGGER ENDPOINTS\n'
                   '# PURPOSE: Azure Functions HTTP API endpoint\n'
                   '# EPOCH: Shared by all epochs (API layer)\n'
                   '# TODO: Audit for framework logic that may belong in CoreMachine')
    },

    # Cross-Cutting Utilities
    'UTILITIES': {
        'files': [
            'utils/__init__.py',
            'utils/contract_validator.py',
            'utils/import_validator.py',
        ],
        'marker': ('# CATEGORY: CROSS-CUTTING UTILITIES\n'
                   '# PURPOSE: Validation and diagnostic utilities used throughout codebase\n'
                   '# EPOCH: Shared by all epochs (utilities)')
    },
}


def update_infrastructure_marker(filepath: Path, new_marker: str) -> bool:
    """Replace old INFRASTRUCTURE marker with new descriptive category."""
    try:
        content = filepath.read_text()

        # Pattern to match old infrastructure marker
        old_pattern = r'# EPOCH: INFRASTRUCTURE\n# STATUS: Core infrastructure - shared by all epochs\n'

        if re.search(old_pattern, content):
            # Replace old marker with new one
            new_content = re.sub(old_pattern, new_marker, content)
            filepath.write_text(new_content)
            print(f"  ✅ Updated: {filepath}")
            return True
        else:
            print(f"  ⏭️  No old marker found: {filepath}")
            return False

    except Exception as e:
        print(f"  ❌ Error updating {filepath}: {e}")
        return False


def main():
    print('=' * 70)
    print('UPDATING TO DESCRIPTIVE CATEGORIES')
    print('=' * 70)
    print()

    base_dir = Path('.')
    total_updated = 0

    for category_name, category_info in CATEGORIES.items():
        files = category_info['files']
        marker = category_info['marker']

        print(f"{category_name} ({len(files)} files)")

        for filepath in files:
            path = base_dir / filepath
            if path.exists():
                if update_infrastructure_marker(path, marker):
                    total_updated += 1

        print()

    print('=' * 70)
    print(f'COMPLETE - {total_updated} files updated')
    print('=' * 70)


if __name__ == '__main__':
    main()
