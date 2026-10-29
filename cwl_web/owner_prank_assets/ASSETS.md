# Owner prank image manifest

These images are backend-owned and served only through the owner-checked `/api/cwl/prank/assets/<name>` route. They are absent from the public frontend assets. The Fan Kit source is [Supercell's official game assets catalog](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets). The signed detail links below came from Ruggie's asset handoff and may expire; the numeric IDs identify the source assets.

Each shipped PNG was cropped to pixels with alpha greater than 60, resized proportionally to 340 px tall, and encoded as WebP at quality 86 (method 6). Every file is below 120 KB. The final Archer Queen used the same alpha crop and height pipeline. The GIF is loaded directly from Tenor in the frontend and is not stored here.

| Served file | Observed character and pose | Cards | Source | Bytes | SHA-256 |
|---|---|---:|---|---:|---|
| `78096.webp` | Anime Wizard, pointing/yelling | 3 | Fan Kit ID 78096 ([catalog](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets)); source `Anime_Wizard_02.png` | 27,554 | `05ef06499ae850f5de076566aa158176ad3bc35d70974d4381626d55201cb068` |
| `97730.webp` | Stern Grand Warden, chosen over raised-hand pose | 4, 8, 9 | [Fan Kit ID 97730](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6OTc3MzAsInNjb3BlIjoiYXNzZXQ6dmlldyIsInRpbWVzdGFtcCI6IjE3OTMyODk4MjIifQ:supercell:qSJyV-T5Yw_Gd1VKoVkA0K2BItT6ZEeOk6jqCU3ScE4); source `GW_DarkDays_f32_2k_V2.png` | 13,836 | `3eb7bc8f0ed9fabacdcfddd7f0d2988cf99d067d88ba3be44412faaf5e0f4f9b` |
| `102860.webp` | Worried Builder, chosen over Apprentice Builder | 5 | Fan Kit ID 102860 ([catalog](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets)); source `Builder_04.png` | 22,200 | `fc2fb41f763d0e72e1cd74828d1b00f2a07a87d6ff2ef75c61eab599bec66fc7` |
| `97711.webp` | Archer Queen, Dark Days pose | 6 | [Fan Kit ID 97711](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6OTc3MTEsInNjb3BlIjoiYXNzZXQ6dmlldyIsInRpbWVzdGFtcCI6IjE3OTMyOTAwNjgifQ:supercell:i1TKzI_lAJpYEaaVssitg1JrvcPE4Beoys3ajuupE6Y); source `ArcherQueen_DarkDays_f60_withGroundShadows.png` | 14,360 | `b06f80e7fb21d009d74d8a6d02b2787f616f1cc75ea4727f105f044d84043f89` |
| `160053.webp` | Grand Mage / Grand Warden styling, dramatic stance | 7 | [Fan Kit ID 160053](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6MTYwMDUzLCJzY29wZSI6ImFzc2V0OnZpZXciLCJ0aW1lc3RhbXAiOiIxNzkzMjg5MTY3In0:supercell:sdhfpnfr0uPvWRgVgVwIjZqTvn7WjA79VbJ5AWSWiZk); source `Grand _Mage_pose01_shadow.png` | 26,320 | `5f862690bbb9511d23fea13af1fa7f807889daf9867ce413505bca7dd1413b7b` |
| `102809.webp` | Goblin, mischievous avatar | 10, 11 | [Fan Kit ID 102809](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6MTAyODA5LCJzY29wZSI6ImFzc2V0OnZpZXciLCJ0aW1lc3RhbXAiOiIxNzkzMjg5NzA5In0:supercell:XbJYBg7u-ERH3JQf6R1Y56zQN1VOm3UWHeUB4o3R4co); source `Goblin_avatar.png` | 18,054 | `f16c8e52a40b5fe6bb1e142f20d65fb7cb1299f56ffcb5e61cafb30c0fa12f0f` |
| `102888.webp` | Minion, purple encore | 12 | [Fan Kit ID 102888](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6MTAyODg4LCJzY29wZSI6ImFzc2V0OnZpZXciLCJ0aW1lc3RhbXAiOiIxNzkzMjg5NTkxIn0:supercell:FZaxYWUVuaRp58DJPcwBU7TW3vzWsszt_yXjcR0DNa4); source `minion.png` | 21,784 | `8be84b356ff3a5140d1334c9a3e67760c8cb2551f36dc3bec9377f5f3764ab59` |
| `102845.webp` | Baby Dragon, smug pose | 13, 14 | [Fan Kit ID 102845](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6MTAyODQ1LCJzY29wZSI6ImFzc2V0OnZpZXciLCJ0aW1lc3RhbXAiOiIxNzkzMjkwMjA0In0:supercell:YUg0D1OgEYMuetxGLeGrPotPqPi60xiDIr7nPHTGAZQ); source `Baby Dragon_02.png` | 21,442 | `4d47d6ca49475001b9fe56c4fab1b4442e5a6bd16cc1cad5770dfe48a6321202` |
| `final-aq.webp` | Archer Queen, Ruggie's supplied cutout | 15 | Ruggie's own `AQ-removebg-preview.png`; **not from the Fan Kit** | 23,642 | `711359a79a286f5074649e1db3ff2023f200f129783e2fe31340f8cd8da0cda3` |

Inspected but rejected alternatives (their generated WebP files are not shipped or allowed by the route):

| Fan Kit ID | Observed image | Reason |
|---|---|---|
| [97724](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6OTc3MjQsInNjb3BlIjoiYXNzZXQ6dmlldyIsInRpbWVzdGFtcCI6IjE3OTMyODk4NjAifQ:supercell:xPM4eeaMrVCrH4xRXcfjM4Am5jBf5AUPClo5S5cal64) | Grand Warden with a raised hand (`GW_DarkDays_f101_2k_v2.png`) | The stern 97730 pose better fits judgment and the loyalty speech. |
| [79701](https://fankit.supercell.com/d/vkEdmkUCngKw/game-assets/show/eyJpZCI6Nzk3MDEsInNjb3BlIjoiYXNzZXQ6dmlldyIsInRpbWVzdGFtcCI6IjE3OTMyODg4NjAifQ:supercell:R9F_qs9Cu2ar3OydgyKrNFLlq_x5LbzaPMGtNPQecDY) | Apprentice Builder (`Apprentice_Builder_HV_Gothic_05.png`) | The worried 102860 Builder better fits card 5's disappointment. |
