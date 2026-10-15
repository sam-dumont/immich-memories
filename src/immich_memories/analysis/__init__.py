"""Selection: the story-first editorial route, its readings, banks and source model.

One package per pipeline stage, each importing only the stages below it (`make arch-check`):

- `runtime`: Composition: from `SmartPipeline` to the planner, with the production ports wired in.
- `structure`: The film's structure, planned and finished: the pass that turns material into a cut.
- `polish`: The thin model layer: one read of a rules draft, polished instead of re-planned.
- `selection`: Funded stories become admitted carriers: votes, standing, look-alikes, depth and trim.
- `stories`: The period account read into weighed stories, by a model or by the rules reader.
- `film`: The film's brief and working material: what the planner is asked and what it reads.
- `audience`: Who may see a picture: detector holds, exposure chains, the audience reader and Laya.
- `special_days`: Which days had something happen on them, and what each one may be called.
- `reading`: Banked facts read into text: annotation lines, dated episodes, moments and period accounts.
- `preparation`: The facts each picture owes, produced and banked before a film is read.
- `captions`: The optional caption producer: its request wire, the measured contract and banked outcomes.
- `clips`: What a kept clip plays: its timing budget, motion, window and speech.
- `facts`: What a picture's banked facts say, read without a model.
- `sources`: What a film may use: the discovery pool for one window, album or household.
- `corpus`: The admitted corpus every editorial pass reads, and what keeps a source out of it.
- `places`: Where pictures were taken: place names, home, and the trips away from it.
- `judgments`: Bounded text judgments over the transport: what a stage asks and how its answer is read.
- `llm`: The model transport every reader asks through.

A stage reaches another only through the modules that stage lists in its `__all__`.
"""
