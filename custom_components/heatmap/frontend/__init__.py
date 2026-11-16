"""Static path + Lovelace resource registration."""
from pathlib import Path
from homeassistant.components.http import StaticPathConfig
from homeassistant.helpers.event import async_call_later
from ..const import JSMODULES,URL_BASE
class JSModuleRegistration:
    def __init__(self,hass): self.hass=hass; self.lovelace=hass.data.get("lovelace")
    async def async_register(self):
        try: await self.hass.http.async_register_static_paths([StaticPathConfig(URL_BASE,Path(__file__).parent,False)])
        except RuntimeError: pass
        mode=getattr(self.lovelace,"mode",getattr(self.lovelace,"resource_mode","yaml"))
        if mode=="storage": await self._async_wait()
    async def _async_wait(self):
        async def check(_now):
            if self.lovelace.resources.loaded: await self._register()
            else: async_call_later(self.hass,5,check)
        await check(0)
    async def _register(self):
        existing=list(self.lovelace.resources.async_items())
        for m in JSMODULES:
            url=f"{URL_BASE}/{m['filename']}"; found=next((r for r in existing if r["url"].split("?")[0]==url),None)
            data={"res_type":"module","url":f"{url}?v={m['version']}"}
            if found:
                if found["url"]!=data["url"]: await self.lovelace.resources.async_update_item(found["id"],data)
            else: await self.lovelace.resources.async_create_item(data)
