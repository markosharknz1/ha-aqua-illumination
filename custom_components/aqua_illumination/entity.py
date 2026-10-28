"""Shared base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AquaCoordinator


class AquaEntity(CoordinatorEntity[AquaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AquaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial}_{key}"
        ident = coordinator.identity
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.serial)},
            manufacturer="Aqua Illumination",
            model=f"{ident.get('product', 'Prime')} {ident.get('product_type', '')}".strip(),
            sw_version=ident.get("firmware"),
            serial_number=coordinator.serial,
            name=f"AI {ident.get('product', 'Prime')} {coordinator.serial[-4:]}",
            configuration_url=f"http://{coordinator.client.host}/",
        )
