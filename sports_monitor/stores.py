from dataclasses import dataclass


@dataclass(frozen=True)
class Store:
    key: str
    name: str
    root: str
    listings: tuple[str, ...]
    # A disabled store is never fetched; it is reported with its reason.
    # Re-enable only after access is permitted, never by working around a block.
    enabled: bool = True
    disabled_reason: str = ''


STORES = (
    Store('barcin', 'Barçın Spor', 'https://www.barcin.com', ('/outlet/',)),
    Store('sporjinal', 'Sporjinal', 'https://www.sporjinal.com', ('/kadin/', '/erkek/', '/cocuk/')),
    # Best-effort public pages; robots.txt allows these listing and product paths.
    Store('sneaks', 'Sneaks Up', 'https://www.sneaksup.com', ('/sezon-sonu-indirimi',)),
    Store('superstep', 'SuperStep', 'https://www.superstep.com.tr', ('/indirim/',)),
    Store('sportive', 'Sportive', 'https://www.sportive.com.tr', ('/outlet/',)),
    Store('koray', 'Koray Spor', 'https://www.korayspor.com', ('/erkek-indirimli-urunler/', '/kadin-indirimli-urunler/', '/cocuk-indirimli-urunler/')),
    Store('yali', 'Yalı Spor', 'https://www.yalispor.com.tr', ('/tum-urunler?sirala=fiyat_azalan&sezon=indirimdekiler',),
          enabled=False,
          disabled_reason='Membership agreement restricts automated loading/copying of site data; '
                          'disabled until access is permitted or authorized'),
    # Best-effort public pages only; never call the robots-disallowed availability API.
    Store('adidas', 'adidas Türkiye', 'https://www.adidas.com.tr', ('/tr/outlet',)),
)
NAMES = {s.key: s.name for s in STORES}
