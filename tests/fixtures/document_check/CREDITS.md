# Where the document check pictures come from

The document check must hold maps out of films and keep photographs of real ground seen from
above. These are public examples of both, from Wikimedia Commons, each under CC0 1.0 or CC BY
(3.0 or 4.0) as its own Commons page states. They are scaled to 640 px on the long side and
stripped of metadata. The aerial views of a harbour town from a summit come from the demo library
(`tests/e2e/fixtures/library`, credited in its own `CREDITS.md`) and are read from there.

`measured.json` holds what the pinned document head and frame head answered on each picture and
whether the check must hold it. `tests/test_document_check_maps.py` replays it through the
selection read; `tests/integration/photos/test_document_check_models.py` runs the real models
again to prove the record.

| File | Title | Author | Source | Licence |
| --- | --- | --- | --- | --- |
| `aerial-coastline-drone.jpg` | Coastline drone view (Unsplash).jpg | Tim Gouw punttim | https://commons.wikimedia.org/wiki/File:Coastline_drone_view_(Unsplash).jpg | CC0 |
| `aerial-drone-houses.jpg` | Drone view of houses (Unsplash).jpg | Richard Horne richardhorne | https://commons.wikimedia.org/wiki/File:Drone_view_of_houses_(Unsplash).jpg | CC0 |
| `aerial-lake.jpg` | Sheridan Lake, Colorado aerial view (2025).jpg | Quintin Soloviev | https://commons.wikimedia.org/wiki/File:Sheridan_Lake,_Colorado_aerial_view_(2025).jpg | CC BY 4.0 |
| `map-board-irchel.jpg` | Board Irchel.jpg | Thomasox58 | https://commons.wikimedia.org/wiki/File:Board_Irchel.jpg | CC0 |
| `map-board-ohori-park.jpg` | Ōhori Park The map on the information board Ōhorikōen Chūō-ku Fukuoka 20260609.jpg | Hirho | https://commons.wikimedia.org/wiki/File:%C5%8Chori_Park_The_map_on_the_information_board_%C5%8Chorik%C5%8Den_Ch%C5%AB%C5%8D-ku_Fukuoka_20260609.jpg | CC BY 4.0 |
| `map-board-trail.jpg` | Information board on hiking trail La Via del Bitto, between Lecco and Morbegno.jpg | Kaitu | https://commons.wikimedia.org/wiki/File:Information_board_on_hiking_trail_La_Via_del_Bitto,_between_Lecco_and_Morbegno.jpg | CC0 |
| `map-printed-changwon.jpg` | Tourist Map Changwon 2004.jpg | Ossewa | https://commons.wikimedia.org/wiki/File:Tourist_Map_Changwon_2004.jpg | CC BY 4.0 |
| `map-scanned-newcastle-1941.jpg` | Topographic map - Newcastle - 1941.jpg | Australian Survey Corps prepared from aerial photos | https://commons.wikimedia.org/wiki/File:Topographic_map_-_Newcastle_-_1941.jpg | CC0 |
| `map-screenshot-plant-distribution.jpg` | Screenshot-powo-Chrysojasminum-distribution map-2023-november-28.png | The International Plant Names Index and World Checklist of Vascular Plants 2023. Published on the Internet at http://www.ipni.org and https://powo.science.kew.org/ | https://commons.wikimedia.org/wiki/File:Screenshot-powo-Chrysojasminum-distribution_map-2023-november-28.png | CC BY 3.0 |
| `map-screenshot-wikipedia-us.jpg` | Russian Wikipedia screenshot (US map).jpg | Clarettt | https://commons.wikimedia.org/wiki/File:Russian_Wikipedia_screenshot_(US_map).jpg | CC0 |
| `map-topographic-kansai.jpg` | Topographic map of Kansai.webp | Soren Bradley | https://commons.wikimedia.org/wiki/File:Topographic_map_of_Kansai.webp | CC0 |
| `map-topographic-shikoku.jpg` | Topographic map of Shikoku, Japan.webp | Soren Bradley | https://commons.wikimedia.org/wiki/File:Topographic_map_of_Shikoku,_Japan.webp | CC0 |
