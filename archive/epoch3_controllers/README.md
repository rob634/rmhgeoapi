# Epoch 3 Controllers Archive

**Archived**: 30 SEP 2025
**Reason**: Replaced by Epoch 4 CoreMachine + declarative jobs pattern

---

## Controllers That Will Be Archived Here

Once Epoch 4 is validated, these files will be moved here:

### Confirmed for Archive:
- `controller_base.py` (2,290 lines) - God Class, replaced by CoreMachine
- `controller_hello_world.py` - Queue Storage version
- `controller_container.py` - Queue Storage version
- `controller_stac_setup.py` - Needs refactor anyway
- `controller_factories.py` - Replaced by jobs/registry.py
- `registration.py` - Replaced by new registries

### Kept as Reference (Until CoreMachine Validated):
- `controller_service_bus_hello.py` - Active reference for CoreMachine extraction
- `controller_service_bus_container.py` - Stub, may be needed

---

## Migration Process

1. ✅ Archive folder created (30 SEP 2025)
2. ⏳ CoreMachine implementation (in progress)
3. ⏳ HelloWorld declarative job created
4. ⏳ End-to-end testing validation
5. ⏳ Move controllers here (after validation)

---

Files will be moved here during Phase 6 of EPOCH4_IMPLEMENTATION.md
