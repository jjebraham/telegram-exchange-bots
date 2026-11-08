#!/usr/bin/env python3
"""Verify curated Commons illustrations without publishing or using a model."""
from pathlib import Path
import tempfile

import instagram_reel_commons as commons


def main():
    cases = (
        ('Bitcoin', 'Bitcoin market update'),
        ('AI', 'ChatGPT and Claude artificial intelligence'),
        ('Cybersecurity', 'Cryptocurrency exchange hacked by attackers'),
    )
    verified = 0
    with tempfile.TemporaryDirectory(prefix='kiani-commons-preview-') as tmp:
        for number, (name, title) in enumerate(cases):
            directory = Path(tmp) / str(number)
            directory.mkdir()
            topic = commons._topic({'title_original': title})
            try:
                images = commons.collect({'title_original': title}, directory, limit=1,
                                         seconds=15, _curated_only=True)
                pins = commons.CURATED.get(topic[0], {})
                curated = [item for item in images if item.get('title') in pins]
                if curated:
                    item = curated[0]
                    print(name + ': verified | ' + item['title'] + ' | ' + item['license'])
                    verified += 1
                else:
                    print(name + ': no verified curated image in this check')
            except Exception as exc:
                print(name + ': check unavailable | ' + type(exc).__name__)
    print('Curated topics verified:', verified, 'of', len(cases))
    if not verified:
        raise RuntimeError('No curated image could be verified from Commons; activation stopped.')
    print('Live Commons check passed; no model or Instagram request made.')


if __name__ == '__main__':
    main()
