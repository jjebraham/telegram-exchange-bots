"""Fetch a reviewed Commons soundtrack and retain its attribution evidence."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import secrets
import unicodedata
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import Request, build_opener, HTTPRedirectHandler

API = 'https://commons.wikimedia.org/w/api.php'
UA = 'KianiExchangeInstagramReels/1.0 (https://kiani.exchange)'
TRACKS = (
    {'title': 'File:Rafael Krux - The Epic 2.ogg', 'name': 'The Epic 2',
     'sha1': '2fe54b6a30343251ad8b79f98cc1a6d82164deb0', 'moods': ('uplifting', 'energetic'),
     'artist': 'Rafael Krux'},
    {'title': 'File:Epic Trailer by Rafael Krux.ogg', 'name': 'Epic Trailer',
     'sha1': '09b2ea708abb01b4a292f50d47f178eb04ac5b79', 'moods': ('tense',),
     'artist': 'Rafael Krux'},
    {'title': 'File:Sascha ende - Epic Intro 2019 (cc by) (Filmmusic).oga',
     'name': 'Epic Intro 2019', 'sha1': '868acd3c3340766f805d5595a1caacae63c352b0',
     'moods': ('energetic', 'uplifting'), 'artist': 'Sascha Ende'},
    {'title': 'File:Fantasy Chamber Adventure by Rafael Krux.ogg',
     'name': 'Fantasy Chamber Adventure',
     'sha1': 'e48e720f1ee5f4c0a1271108c8e5179d92f16c28',
     'moods': ('energetic', 'uplifting'), 'artist': 'Rafael Krux'},
    {'title': 'File:The Entertainer by Kevin MacLeod.ogg', 'name': 'The Entertainer',
     'sha1': '45111a083a1d5ea88142e4813a6727320cca5d4f',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Breaking News 5 by Sascha Ende.ogg', 'name': 'Breaking News 5',
     'sha1': 'eefdd12c493a519bd3f16674dcd0f9650475611f',
     'moods': ('tense',), 'artist': 'Sascha Ende'},
    {'title': 'File:Alexander Nakarada - Winter Night (cc-by) (filmmusic).ogg',
     'name': 'Winter Night',
     'sha1': 'a53fbbd3742f72e0906747e1a7f5036c3e56efe2',
     'moods': ('tense', 'uplifting'), 'artist': 'Alexander Nakarada'},
    {'title': 'File:Wholesome by Kevin MacLeod.ogg', 'name': 'Wholesome',
     'sha1': '26ce5b020ad048a92ad6dca5f1dd10741b1831a8',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Sneaky Snitch by Kevin MacLeod.ogg', 'name': 'Sneaky Snitch',
     'sha1': 'e30579458cd3d1104484ac49a2fcc478f0388b96',
     'moods': ('tense',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Cheery Monday by Kevin MacLeod.ogg', 'name': 'Cheery Monday',
     'sha1': 'e5dfc8015e9f05f3faa854a5305c94d7c65dd22d',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:1984 by Frank Schroeter.ogg', 'name': '1984',
     'sha1': '21ebb2f80ffc3700ca5970df67760aedce84171b',
     'moods': ('energetic', 'tense'), 'artist': 'Frank Schroeter'},
    {'title': 'File:Driving to the Night by Frank Schroeter.ogg',
     'name': 'Driving to the Night',
     'sha1': 'c4187b08f23339d6ba638887e4fe55f66b9790a4',
     'moods': ('energetic',), 'artist': 'Frank Schroeter'},
    {'title': 'File:Ancient Rite by Kevin MacLeod.ogg', 'name': 'Ancient Rite',
     'sha1': '2b4a5f8be535e2b0da873f2cc2fdfeec9b8b60ab',
     'moods': ('tense',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:The Descent by Kevin MacLeod.ogg', 'name': 'The Descent',
     'sha1': '6b8bf57de9e9624816686b2f3dde46d62a108f38',
     'moods': ('tense', 'energetic'), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Elf Meditation Preview by Kevin MacLeod.ogg',
     'name': 'Elf Meditation Preview',
     'sha1': '4897c367300021acaff2874c770e80cbda116f7d',
     'moods': ('tense',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Maple Leaf Rag by Kevin MacLeod.ogg', 'name': 'Maple Leaf Rag',
     'sha1': 'a4a0463bc781240933b10a768cbea53286cc548b',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Strength Of The Titans by Kevin MacLeod.ogg',
     'name': 'Strength Of The Titans',
     'sha1': 'd4b3547e6212cf07311039956871e62a381f8e50',
     'moods': ('energetic',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Journey To The 80s by Frank Schroeter.ogg',
     'name': 'Journey To The 80s',
     'sha1': 'bb65402cba8e270d4314333b48a3a27f43a9fe6a',
     'moods': ('energetic', 'uplifting'), 'artist': 'Frank Schroeter'},
    {'title': 'File:Heavy Trailer 5 by Sascha Ende.ogg', 'name': 'Heavy Trailer 5',
     'sha1': 'b22e4d7fa794a978af4547a615d1e82cba681e3b',
     'moods': ('tense', 'energetic'), 'artist': 'Sascha Ende'},
    {'title': 'File:Frogs Legs Rag by Kevin MacLeod.ogg', 'name': 'Frogs Legs Rag',
     'sha1': '94f37c783eeb19d44a3528ff2ab7e7d7e5cd698b',
     'moods': ('uplifting',), 'artist': 'Kevin MacLeod'},
    {'title': 'File:Rafael Krux - Uplifting Blockbuster (cc-by) (filmmusic).mp3', 'name': 'Uplifting Blockbuster', 'sha1': 'd6048333cd7a0bfe75f8b4425f09b959bd360c8f', 'moods': ['tense', 'energetic', 'uplifting'], 'artist': 'Rafael Krux', 'credit': 'Rafael Krux', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Epic Drone Shots 001 by Sascha Ende.mp3', 'name': 'Epic Drone Shots 001', 'sha1': 'f228f9b3c9875bf0cfb1041b262ff3546d31276a', 'moods': ['energetic'], 'artist': 'Sascha Ende', 'credit': 'Sascha Ende', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Inspire Action by Yuri Megis.ogg', 'name': 'Inspire Action', 'sha1': '0ea78bf7557126905b6525684282f29957aa390a', 'moods': ['energetic', 'uplifting'], 'artist': 'Yuri Megis', 'credit': 'Yuri Megis', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:Rust Rebellion by Sascha Ende.mp3', 'name': 'Rust Rebellion', 'sha1': '30ca7308dc12f6c8f8edf47431541e79bada57e1', 'moods': ['energetic'], 'artist': 'Sascha Ende', 'credit': 'Sascha Ende', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Sascha Ende - Cybertrooper (the better version) (cc-by).mp3', 'name': 'Cybertrooper (the better version)', 'sha1': 'f6094b304e66d767da6006adecd72c54692e12c4', 'moods': ['energetic'], 'artist': 'Sascha Ende', 'credit': 'Sascha Ende', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:The March Of The Final Battle by MusicLFiles.ogg', 'name': 'The March Of The Final Battle', 'sha1': '8c0ceb613bbd641ac8dd3b21fde6b8d8b3398577', 'moods': ['tense', 'energetic'], 'artist': 'MusicLFiles', 'credit': 'MusicLFiles', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:Uniq - Art Of Silence V2.ogg', 'name': 'Art Of Silence V2', 'sha1': '48554b845c2c939f59e29819106c0cf59da77a89', 'moods': ['tense'], 'artist': 'Uniq', 'credit': 'Uniq', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:Action (ISRC USUAN1100338).mp3', 'name': 'Action', 'sha1': '27094aac5f03a7acf59f2140a18b542cade12f84', 'moods': ['tense', 'energetic'], 'artist': 'Kevin MacLeod', 'credit': 'Kevin MacLeod', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Alexander Nakarada - Countdown (cc-by) (filmmusic).mp3', 'name': 'Countdown', 'sha1': '3509325db3857ac89dd315caa8f2cd732e3b7c28', 'moods': ['tense'], 'artist': 'Alexander Nakarada', 'credit': 'Alexander Nakarada', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-ashesofanempire.mp3', 'name': 'Ashes Of An Empire', 'sha1': '60c65f5bc06f3e8753107e1667016425c363d5e1', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-epicseries.mp3', 'name': 'Epic Series', 'sha1': '7b3b606e6252c2183c022ae690dced9b90eac8a7', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-epictvtheme.mp3', 'name': 'Epic Tv Theme', 'sha1': '32c07253e711f77843dd67a6d9e51d470d2e05d4', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-gonotgentlyredux.mp3', 'name': 'Go Not Gently Redux', 'sha1': 'c22ad57d2fe4ffc63af6e0c07d259250e76dd6f5', 'moods': ['tense', 'energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-heavyaction.mp3', 'name': 'Heavy Action', 'sha1': '86a5e64b5dc61032832ce1ec21b5d05efedece10', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-hightension.mp3', 'name': 'High Tension', 'sha1': '27ad383460915e2b0636082f26bc9eb034041802', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-inaworld.mp3', 'name': 'In A World', 'sha1': '0fe756d7f7ffe746be94438505dbf40f45e4e741', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-legendsoftheriver.mp3', 'name': 'Legends Of The River', 'sha1': '34272e312eb3da3a1dedfccbb5538d4960b75736', 'moods': ['tense', 'energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-marauder.mp3', 'name': 'Marauder', 'sha1': '162a24120446dd87d6ed65d89421d14f71f55082', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-moderncombat.mp3', 'name': 'Modern Combat', 'sha1': 'a6ecb947a0d3fb7acb4738641ca7237da99aef51', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-movietheme1.mp3', 'name': 'Movie Theme 1', 'sha1': '87b57f13f8d1d1de44944111859f5941f3954b42', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-pinksglass.mp3', 'name': "Pink's Glass", 'sha1': 'c02e16c76c68fed6f6536dd19432dfe43db4f920', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-remembertheheroes.mp3', 'name': 'Remember The Heroes', 'sha1': '29eabe48f5e62ff3afd449700b0c0920e92e377d', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-roadtokilcoo.mp3', 'name': 'Road To Kilcoo', 'sha1': '11a6056565679e471c0474f86485a60bb374c50e', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-rocker.mp3', 'name': 'Rocker (ac/dc Style)', 'sha1': '7da87e35b5501f5c0b7a9477c81303d79bb3538d', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-rocktune.mp3', 'name': 'Nickel Rock', 'sha1': '62a9dab24356a1665f9f3e4de358f41bd2a3bb80', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-searchanddestroy.mp3', 'name': 'Search And Destroy', 'sha1': '007e10708186a99bec9e588bce6bd1a5aee96ab0', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-seriousdrama.mp3', 'name': 'Serious Drama', 'sha1': '1c1278ac4526321062c020d0bcdfcd0d879fe407', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-sittingbull.mp3', 'name': 'Sitting Bull', 'sha1': '46e0c5ec3fee9b58ab7f7149f8e83d0a015b1566', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-sodramatic.mp3', 'name': 'So Dramatic', 'sha1': 'aa39dedf789110e891b7eb2e3b9401d2315d64f9', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-stalkingprey.mp3', 'name': 'Stalking Prey', 'sha1': 'ee1d410e04d9fc3b0afcab867541fad838e6e0e6', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-texastechno.mp3', 'name': 'Texas Techno', 'sha1': 'c590e171f955c261cd35fbf4aedd38d97ac4d6d2', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-theangelsweep.mp3', 'name': 'The Angels Weep', 'sha1': 'e6aa0085da23def4fa2dfc336ecb6dea57694ec2', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-thedeadlyyear.mp3', 'name': 'The Deadly Year', 'sha1': '77a13bf3a4b6f3b3f5ad47933f70c2d6eb17c0e8', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-thegreatunknown.mp3', 'name': 'The Great Unknown', 'sha1': 'ac48888509753a57301e508523ab7c24dea4cb07', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-thevoyage.mp3', 'name': 'The Voyage', 'sha1': 'eb16cc3cf045c62d9169192e1630f0648b7b851e', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-timepassingby.mp3', 'name': 'Time Passing By', 'sha1': 'a43162fa8793d31c87caaf12bda11d22b2ee9565', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-tvdramaversion1.mp3', 'name': 'Tv Drama Theme V1', 'sha1': 'ae31271d7a195b2fe3d791f10b6391d42b00b497', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-tvdramaversion2.mp3', 'name': 'Tv Drama Theme V2', 'sha1': 'bd11d9af4997d9d742c6cf2d4aec6d7a228a5814', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Rafael Krux - Inspiring Advertising - Upbeat Summer Corporate (cc-by) (filmmusic).mp3', 'name': 'Inspiring Advertising - Upbeat Summer Corporate', 'sha1': 'adfd842cdd245b5f1072b867f2c746f0b60843b3', 'moods': ['energetic', 'uplifting'], 'artist': 'Rafael Krux', 'credit': 'Rafael Krux', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Rafael Krux - Inspiring Teaser (cc-by) (filmmusic).mp3', 'name': 'Inspiring Teaser', 'sha1': '450f9f5427ee40b523b7d86a2dc4361c83070784', 'moods': ['energetic', 'uplifting'], 'artist': 'Rafael Krux', 'credit': 'Rafael Krux', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Scott Buckley - Sanctuary.oga', 'name': 'Sanctuary', 'sha1': '56af9f03ec71c6e1a64b312d3083712a9a6c06f8', 'moods': ['tense', 'energetic'], 'artist': 'Scott Buckley', 'credit': 'Scott Buckley', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:Soft Corporate by MusicLFiles.ogg', 'name': 'Soft Corporate', 'sha1': '77bf5ee67761c048fa0c035fa6908a1ace623e85', 'moods': ['uplifting'], 'artist': 'MusicLFiles', 'credit': 'MusicLFiles', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:WinnieTheMoog - Medicine.ogg', 'name': 'Medicine', 'sha1': '90fc00875dbdfe0ea2377dc2caf9176bd9e7d7eb', 'moods': ['energetic', 'uplifting'], 'artist': 'WinnieTheMoog', 'credit': 'WinnieTheMoog', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:WinnieTheMoog - Space Energy (cc-by) (filmmusic).mp3', 'name': 'Space Energy', 'sha1': 'bcbc9e540195c8501a3161ba63477f098d51e148', 'moods': ['energetic', 'uplifting'], 'artist': 'WinnieTheMoog', 'credit': 'WinnieTheMoog', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': "File:Zero-project - Metamorphosis (short trailer's music).ogg", 'name': "Metamorphosis (short trailer's music)", 'sha1': '805d23cdf74bb6b7f89a9ef084f2870d24fb0c3d', 'moods': ['energetic'], 'artist': 'zero-project', 'credit': 'zero-project', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:A Moments Reflection.mp3', 'name': 'Winter', 'sha1': 'a43fe1193d08730aaa5ae7f31dfa4b17335973dc', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-abrighterheart.mp3', 'name': 'A Brighter Heart', 'sha1': '1009384b2eb44444b3d77493029948fe7b537b2c', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-actthree.mp3', 'name': 'Act Three', 'sha1': 'e966d704b7b708b238b0a24bdb671e397d893f6b', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-atallship.mp3', 'name': 'A Tall Ship', 'sha1': '4c01759011cdb82714b21043068c73e7151600a5', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-azimuth.mp3', 'name': 'Azitmuth', 'sha1': '46957f753c067ca686f97cdda7e8e11a7faf78b9', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-banjohop.mp3', 'name': 'Banjo Hop', 'sha1': '5f674a9049c40cff7e4b06985703b536b61d0b2c', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-bridesballad.mp3', 'name': "Bride's Ballad", 'sha1': '03db472827674bb665962a59bdcda5d9027660e9', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-egyptiancrawl.mp3', 'name': 'Egyptian Crawl', 'sha1': '8b355f44c460a977b02f1dcee81d9a3fabdf0116', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-emilywalksaway.mp3', 'name': 'Emily Walks Away', 'sha1': '51f18e338132d2b1f7c7732056ad6a32f5188ac6', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-eventhorizon.mp3', 'name': 'Event Horizon', 'sha1': '2870f4a872bc888624f3ff50299223b1f186fdb8', 'moods': ['tense', 'energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-gonotgently.mp3', 'name': 'Go Not Gently', 'sha1': 'a670971bceb8677dbfcabfc3593af2ab4f569de6', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-grandevista.mp3', 'name': 'Grand Vista', 'sha1': '7975580ba8b2e6040835d2dbce6cd977b70e3f63', 'moods': ['tense', 'energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-hopeagainsthope.mp3', 'name': 'Hope Against Hope', 'sha1': '3cef4af86a6247d6a65fbcaf95e4b8243cc2de12', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-horrorepic.mp3', 'name': 'Horror Epic', 'sha1': '8f29e566a58add176f99a222f106c45831eaeeca', 'moods': ['tense', 'energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-lightningbugs.mp3', 'name': 'Lightning Bugs', 'sha1': 'ab53992d47d97fc6b61372ce35bce0fcea847931', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-majesticpiano.mp3', 'name': 'Majestic Piano', 'sha1': '06e313a6e062a0d2d39f1b4ffd50e796af70356f', 'moods': ['tense', 'energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-marathonman.mp3', 'name': 'Marathon Man', 'sha1': '0c47ae0a8457f3b617a279bad8faba95c7c7ab0b', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-mediumrock.mp3', 'name': 'Medium Rock. Tanzmusik.', 'sha1': '4e0f066b9cb983a476c7393120f1d7cb0926bd21', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-openroad.mp3', 'name': 'Open Road', 'sha1': 'e9bfb9853062a63da7701de3ba9b13341b1e4184', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-opusone.mp3', 'name': 'Opus One', 'sha1': 'c97e9ba84be72176c8d763b0328cb37bc2d0c3fe', 'moods': ['tense', 'energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-pyramids.mp3', 'name': 'Pyramids', 'sha1': 'f5e7e80700db1194ed3a7198c98628e99477d1b6', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-roboskater.mp3', 'name': 'Roboskater', 'sha1': '7ca92197bcefa57995e67d0db84110c9af17ee7e', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-sailorslament.mp3', 'name': "Sailer's Lament", 'sha1': '9b7096277ba5abfe12ce95c7c2256f24c2eb37bb', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-sk8board.mp3', 'name': 'Sk8board', 'sha1': 'e7a68ccc42b2f4e928ecd9ab2b4796979bcc0efd', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-temptationmarch.mp3', 'name': 'Temptation March', 'sha1': '3af089031088ff9460dac49be55b1b6470e9825a', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-thingamajig.mp3', 'name': 'Thingamajig', 'sha1': '8562bd8f96d53e4fdaf2b4741463eacf4f3f07dc', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-troubledbridges.mp3', 'name': 'Troubled Bridges', 'sha1': '82bdfee75d8506df7c53cf269615f77a2b6ad908', 'moods': ['energetic'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-turkishdance.mp3', 'name': 'Turkish Dance', 'sha1': 'b190f7b54f434ea9fc4d45055de363f80676bdcb', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-whatwecame4.mp3', 'name': 'What We Came 4', 'sha1': '7253c76bb34e754d351e16664371441f81eae80f', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Audionautix-com-ccby-worldsaway.mp3', 'name': 'Worlds Away', 'sha1': '522c72b8ae6f52cca59cfa1a05212fabab0f54f1', 'moods': ['energetic', 'uplifting'], 'artist': 'Created by Jason Shaw. Released under Creative Commons Attribution License 3.0. Required credit: "music by audionautix.com". A signed release form is available at http://audionautix.com', 'credit': 'Jason Shaw — music by audionautix.com', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Battlefield Heroes by Sascha Ende.mp3', 'name': 'Battlefield Heroes', 'sha1': '0376b7f92e9432f9fccdbc77bdc66d4d02563393', 'moods': ['tense'], 'artist': 'Sascha Ende', 'credit': 'Sascha Ende', 'license': 'CC BY 4.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Eighties Action (ISRC USUAN1100243).mp3', 'name': 'Eighties Action', 'sha1': '924165840023cc676cd0c54099a8a53ac617db08', 'moods': ['energetic'], 'artist': 'Kevin MacLeod', 'credit': 'Kevin MacLeod', 'license': 'CC BY 3.0', 'mime': 'audio/mpeg'},
    {'title': 'File:Kevin MacLeod ~ Monkeys Spinning Monkeys.ogg', 'name': 'Monkeys Spinning Monkeys', 'sha1': '0a2700730d9b564ae95378028ddc063f1ba83114', 'moods': ['uplifting'], 'artist': 'Kevin MacLeod', 'credit': 'Kevin MacLeod', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:Luca Fraula - Darkness (cc-by) (filmmusic.io).ogg', 'name': 'Darkness', 'sha1': 'aab1554d9e26ba193fc604c7f00811f429ab3aaf', 'moods': ['tense'], 'artist': 'Luca Fraula', 'credit': 'Luca Fraula', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
    {'title': 'File:Otis Galloway - Ghost Ridin (cc-by) (filmmusic.io).ogg', 'name': 'Ghost Ridin', 'sha1': '7ca399dd45182eab9cb0ab217033074284eed2da', 'moods': ['energetic'], 'artist': 'Otis Galloway', 'credit': 'Otis Galloway', 'license': 'CC BY 4.0', 'mime': 'application/ogg'},
)
LIMIT = 10 * 1024 * 1024
LICENSE = 'CC BY 4.0'
LICENSE_URLS = {
    'CC BY 4.0': 'https://creativecommons.org/licenses/by/4.0/',
    'CC BY 3.0': 'https://creativecommons.org/licenses/by/3.0/',
}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _read(url, limit, timeout=15):
    request = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
    with build_opener(NoRedirect()).open(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError('Empty or oversized Wikimedia response')
    return data


def _plain(value):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value))).strip()


_EVENT_TERMS = {
    'tense': ('hack', 'hacked', 'hacker', 'hackers', 'ransomware', 'breach', 'breached',
              'exploit', 'exploited', 'fraud', 'scam', 'sanction', 'sanctions', 'sanctioned',
              'lawsuit', 'arrest', 'arrested', 'theft', 'stolen', 'attack', 'attacked',
              'collapse', 'collapsed', 'bankruptcy', 'crash', 'crashed', 'plunge', 'plunges',
              'vulnerability', 'vulnerabilities', 'malware', 'seized',
              'war', 'terrorism', 'casualties', 'هک', 'هکر', 'هکرها', 'کلاهبرداری', 'سرقت',
              'تحریم', 'تحریمها', 'حمله', 'حملات', 'ورشکستگی', 'سقوط', 'ریزش', 'افت شدید',
              'جنگ', 'نفوذ', 'زیان'),
    'uplifting': ('approval', 'approved', 'approves', 'partnership', 'adoption', 'breakthrough',
                  'recovery', 'recovers', 'recovered', 'milestone', 'collaboration',
                  'پذیرش', 'همکاری', 'تایید', 'تأیید', 'پیشرفت', 'بازیابی', 'بهبود',
                  'توافق', 'موفقیت'),
    'energetic': ('surge', 'surged', 'surges', 'rally', 'rallies', 'soars', 'soared',
                  'record', 'launch', 'launched', 'launches', 'upgrade', 'upgrades',
                  'rise', 'rises', 'rose', 'growth', 'grows', 'gains', 'increase', 'increases',
                  'جهش', 'رکورد', 'رشد', 'افزایش', 'صعود', 'راه اندازی', 'ارتقا'),
}
_PLAYFUL_TITLES = {
    'Monkeys Spinning Monkeys', 'Sneaky Snitch', 'The Entertainer',
    'Frogs Legs Rag', 'Maple Leaf Rag', 'Cheery Monday',
}


def _mood_text(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = text.replace('\u200c', ' ').replace('ي', 'ی').replace('ك', 'ک')
    return re.sub(r'\s+', ' ', text)


def _event_hits(text, terms):
    found = []
    for term in terms:
        normalized = _mood_text(term)
        if re.search(r'(?<!\w)' + re.escape(normalized) + r'(?!\w)', text):
            found.append(term)
    return found


def classify_story(story):
    """Classify the lead event; do not treat generic 'crypto' or 'price' as emotion."""
    headline = _mood_text(' '.join(str(story.get(k) or '') for k in ('title_original', 'title_fa')))
    body = _mood_text(' '.join(str(story.get(k) or '') for k in ('summary_original', 'summary_fa', 'summary')))
    for source, text in (('headline', headline), ('summary', body)):
        if re.search(r'(?:\binflation\b|تورم).{0,35}(?:\brises\b|\bincreases\b|\baccelerates\b|افزایش|شتاب)', text):
            return {'mood': 'tense', 'source': source, 'signals': ['rising inflation']}
        if re.search(r'(?:\binflation\b|تورم).{0,35}(?:\bfalls\b|\beases\b|\bcools\b|کاهش)', text):
            return {'mood': 'uplifting', 'source': source, 'signals': ['easing inflation']}
        matches = {mood: _event_hits(text, terms) for mood, terms in _EVENT_TERMS.items()}
        for mood in ('tense', 'uplifting', 'energetic'):
            if matches[mood]:
                return {'mood': mood, 'source': source, 'signals': matches[mood][:5]}
    return {'mood': None, 'source': 'unclear', 'signals': []}


def select_order(story, previous=None):
    mood = classify_story(story)['mood']
    recent = [previous] if isinstance(previous, str) else list(previous or ())
    recent = [title for title in recent if isinstance(title, str)][:50]
    candidates = list(TRACKS)
    secrets.SystemRandom().shuffle(candidates)
    return sorted(candidates, key=lambda item: (
        bool(mood and mood not in item['moods']),
        item['name'] in _PLAYFUL_TITLES,
        item['title'] in recent,
        bool(mood == 'tense' and 'uplifting' in item['moods']),
        item['moods'].index(mood) if mood in item['moods'] else 0,
        -recent.index(item['title']) if item['title'] in recent else 0,
    ))


def retrieve_track(track, output):
    query = urlencode({'action': 'query', 'format': 'json',
        'prop': 'imageinfo|categories', 'cllimit': 'max',
        'iiprop': 'url|extmetadata|mime|size|sha1', 'titles': track['title']})
    data = json.loads(_read(API + '?' + query, 1024 * 1024))
    pages = list(data['query']['pages'].values())
    if len(pages) != 1 or pages[0].get('title') != track['title']:
        raise ValueError('Unexpected music record')
    categories = [str(item.get('title', '')).casefold()
        for item in pages[0].get('categories', [])]
    if (not categories or any('license review needed' in item or 'fan art' in item
            for item in categories)):
        raise ValueError('Wikimedia Commons license review or fan-art flag is present')
    info = pages[0]['imageinfo'][0]
    meta = info['extmetadata']
    value = lambda key: str(meta.get(key, {}).get('value', '')).strip()
    license_name = track.get('license', LICENSE)
    license_url = LICENSE_URLS.get(license_name)
    mime = track.get('mime', 'application/ogg')
    if (not license_url or mime not in {'application/ogg', 'audio/mpeg'}
            or info.get('sha1') != track['sha1'] or info.get('mime') != mime
            or not 1000 <= info.get('size', 0) <= LIMIT or info.get('duration', 0) < 60
            or value('LicenseShortName') != license_name
            or value('LicenseUrl').rstrip('/') != license_url.rstrip('/')
            or _plain(value('Artist')) != track['artist'] or value('Restrictions')):
        raise ValueError('Music license, attribution or file identity did not match')
    url = info['url']
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'upload.wikimedia.org' or parsed.username or parsed.password or parsed.port:
        raise ValueError('Unexpected audio host')
    description = urlsplit(info['descriptionurl'])
    if (description.scheme != 'https' or description.hostname != 'commons.wikimedia.org'
            or unquote(description.path).replace('_', ' ') != '/wiki/' + track['title']
            or description.query or description.fragment):
        raise ValueError('Unexpected attribution URL')
    raw = _read(url, LIMIT, timeout=25)
    valid_magic = raw.startswith(b'OggS') if mime == 'application/ogg' else (
        raw.startswith(b'ID3') or len(raw) >= 2 and raw[0] == 0xff and raw[1] & 0xe0 == 0xe0)
    if len(raw) != info['size'] or hashlib.sha1(raw).hexdigest() != track['sha1'] or not valid_magic:
        raise ValueError('Music download failed integrity verification')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Music destination already exists')
    with output.open('xb') as handle:
        handle.write(raw)
    output.chmod(0o600)
    return {'title': track['title'], 'name': track['name'], 'artist': track.get('credit', track['artist']),
        'license': license_name, 'license_url': license_url,
        'source_url': info['descriptionurl'], 'sha1': track['sha1'], 'moods': list(track['moods']),
        'changes': 'shortened and faded'}


def caption_credit(info):
    return ('Music: ' + info['name'] + ' — ' + info['artist'] + ' (shortened and faded)\n' +
            info['source_url'] + '\n' + info['license'] + ': ' + info['license_url'])







