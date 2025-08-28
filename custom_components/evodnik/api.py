from __future__ import annotations

import re
import requests
from typing import Any, Dict, List, Optional

BASE = "https://servis.evodnik.cz"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; evodnik-ha/0.2.9)",
}

LOGIN_PATHS = [
    "/Account/Login",
    "/app/Account/Login",
]

def _find_anti_forgery_token(html: str) -> Optional[str]:
    m = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', html, re.IGNORECASE)
    return m.group(1) if m else None

class EvodnikClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    def login(self, username: str, password: str) -> None:
        for path in LOGIN_PATHS:
            url = BASE + path
            r = self._session.get(url, timeout=30)
            if r.status_code != 200:
                continue

            token = _find_anti_forgery_token(r.text) or ""

            data = {
                "__RequestVerificationToken": token,
                "Email": username,
                "UserName": username,
                "Password": password,
                "RememberMe": "false",
            }
            headers = dict(HEADERS)
            headers.update({
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": BASE,
                "Referer": url,
            })
            rp = self._session.post(url, data=data, headers=headers, timeout=30, allow_redirects=True)

            auth_cookie = next((c for c in self._session.cookies if ".AspNet" in c.name and "ApplicationCookie" in c.name), None)
            if auth_cookie and rp.status_code in (200, 302):
                return

        raise RuntimeError("Login failed. Check credentials.")

    def get_device_list(self) -> List[Dict[str, Any]]:
        r = self._session.get(f"{BASE}/app/Device/GetDeviceList", timeout=30)
        r.raise_for_status()
        return r.json()

    def get_devices_headers(self, device_id: int) -> List[Dict[str, Any]]:
        r = self._session.get(
            f"{BASE}/app/Device/GetDevicesHeaders",
            params={"actualizeRecord": "false", "id": device_id},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def get_device_dashboard(self, device_number: int) -> Dict[str, Any]:
        r = self._session.get(
            f"{BASE}/app/Device/DeviceDashboard",
            params={"deviceNumber": device_number, "reportPage": "false"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def fetch_all(self, username: str, password: str, device_id: int) -> Dict[str, Any]:
        self.login(username, password)
        headers = self.get_devices_headers(device_id)
        if not headers:
            raise RuntimeError("Empty GetDevicesHeaders response.")
        hdr = headers[0]
        device_number = hdr.get("DeviceNumber")
        if device_number is None:
            raise RuntimeError("DeviceNumber missing in headers.")
        dashboard = self.get_device_dashboard(device_number)
        return {
            "headers": headers,
            "dashboard": dashboard,
        }
