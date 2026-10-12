# Where the face fixture comes from

The face detector needs a picture with faces and a few without. All of them are
CC0 1.0 (public domain dedication) stock photographs: the picnic from StockSnap.io,
found through the Openverse index, and the six `faceless-*` pictures (a tablecloth,
a garden table, woodland floor, rain on a window) that the e2e library used to hold,
kept because the Haar cascade once read faces into exactly this kind of texture.

| File | Title | Photographer | Source | Licence |
| --- | --- | --- | --- | --- |
| `picnic-friends.jpg` | Friends Picnic | Helena Lopes | https://stocksnap.io/photo/friends-picnic-3IVBNKC2JH | CC0 1.0 |
| `faceless-woods-hamper.jpg` | Table Cloth | Bonnie Kittle | https://stocksnap.io/photo/table-cloth-9G5V9SZOOM | CC0 1.0 |
| `faceless-garden-table.jpg` | Garden Shrubs | Daria Nepriakhina | https://stocksnap.io/photo/garden-shrubs-77AD8564CC | CC0 1.0 |
| `faceless-woods-path.jpg` | Trees Forest | Lukasz Szmigiel | https://stocksnap.io/photo/trees-forest-ZJOY89B3SM | CC0 1.0 |
| `faceless-woods-moss-01.jpg` | Fallen mossy tree trunk crossing a forest trail | Krishna k. sahh | https://commons.wikimedia.org/wiki/File:Fallen_mossy_tree_trunk_crossing_a_forest_trail.jpg | CC0 1.0 |
| `faceless-woods-fern-01.jpg` | Fallen tree and ferns (Unsplash) | Dustin Scarpitti  dusty_blanco | https://commons.wikimedia.org/wiki/File:Fallen_tree_and_ferns_(Unsplash).jpg | CC0 1.0 |
| `faceless-home-rain-window-01.jpg` | Rain on window (Unsplash) | Francesco Gallarotti  gallarotti | https://commons.wikimedia.org/wiki/File:Rain_on_window_(Unsplash).jpg | CC0 1.0 |

Four faces, 960x652, re-encoded at JPEG quality 80 to keep it the size of the
other fixtures. YuNet finds all four; at the shipped score threshold of 0.9 it
keeps three of them.
