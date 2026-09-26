# Fixture provenance

Minimized public product payloads captured on 2026-09-26. Only fields used by
the parsers are retained. These are regression fixtures, never live posting data.

- Barçın: `/nike-dunk-low-retro-erkek-spor-ayakkabi-beyaz-beyaz-siyah/`
- SuperStep: `/urun/lacoste-storm-96-2k-kadin-beyaz-spor-ayakkabi/750sfa0174t/`
- Sporjinal: `/only-sons-ceres-erkek-siyah-esofman-alti-22018686-b-2/`
- Sportive: `/puma-court-classic-clean-kadin-beyaz-sneaker-ayakkabi-40222324/?format=json`
- Koray: `/merrell-ayakkabi-outdoor-ayakkabilari-moab-speed-2-gtx-j037513-10010`
- Sneaks Up: `/adidas-samba-og-ig9030-001-sneaker-p-139139`
- Yalı: `/urun/adidas-ultraboost-5-strung-erkek-spor-ayakkabi-siyah`, embedded
  public product data inspected in the browser; subsequently HTTP scanner worked.

There is no live adidas fixture: this host received HTTP 403. adidas's generic
per-variant JSON-LD fallback is unverified and must not be represented as tested
production coverage.
