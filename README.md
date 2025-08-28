Integrace umožňuje přihlásit se do VTS **https://servis.evodnik.cz** a načítat stav zařízení eVodník (průtoky, režimy, ventil, apod.).
Součástí je i **kumulativní vodoměr** vhodný pro **Energy Dashboard** v Home Assistantu.

---

## 📦 Instalace

### Varianta A – přes HACS (doporučeno)

1. Otevřete **HACS → Integrations**.
2. Klikněte na **⋯ (tři tečky) → Custom repositories**.
3. Přidejte adresu repozitáře a zvolte **Category: Integration**.  
   - https://github.com/AidenShaw2020/evodnik_cloud_ha`
4. V HACS vyhledejte **eVodník** → **Install**.
5. **Restartujte** Home Assistant.
6. Přejděte do **Settings → Devices & Services → Add Integration** a vyhledejte **eVodník**.

> Pokud používáte HACS poprvé, sledujte oficiální postup instalace HACS: https://hacs.xyz/docs/setup/download/

### Varianta B – ruční instalace

1. Stáhněte release ZIP a rozbalte složku `evodnik` do:
   - `config/custom_components/`
2. **Restartujte** Home Assistant.
3. Přejděte do **Settings → Devices & Services → Add Integration** a vyhledejte **eVodník**.
