from dataclasses import dataclass


@dataclass(frozen=True)
class Store:
    key: str
    name: str
    root: str
    listings: tuple[str, ...]


STORES = (
    Store('barcin', 'Barçın Spor', 'https://www.barcin.com', ('/outlet/',)),
    Store('sporjinal', 'Sporjinal', 'https://www.sporjinal.com', ('/kadin/', '/erkek/', '/cocuk/')),
    Store('sneaks', 'Sneaks Up', 'https://www.sneaksup.com', ('/sezon-sonu-indirimi',)),
    Store('superstep', 'SuperStep', 'https://www.superstep.com.tr', ('/indirim/',)),
    Store('sportive', 'Sportive', 'https://www.sportive.com.tr', ('/outlet/',)),
    Store('koray', 'Koray Spor', 'https://www.korayspor.com', ('/erkek-indirimli-urunler/', '/kadin-indirimli-urunler/', '/cocuk-indirimli-urunler/')),
    Store('yali', 'Yalı Spor', 'https://www.yalispor.com.tr', ('/tum-urunler?sirala=fiyat_azalan&sezon=indirimdekiler',)),
    Store('adidas', 'adidas Türkiye', 'https://www.adidas.com.tr', ('/tr/outlet',)),
)
NAMES = {s.key: s.name for s in STORES}
