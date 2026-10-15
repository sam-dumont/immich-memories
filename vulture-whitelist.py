# Read by kaldi-native-fbank's C++ feature extractor. The real FireRedVAD fixture
# tests verify these restored frame settings and the resulting feature scale.
_.dither
_.frame_length_ms
_.frame_shift_ms
_.samp_freq
_.num_bins

# Read by Asset.model_dump in source_metadata_digest (analysis/
# clips/bound_sample.py), which hashes the whole model to bind the source
# metadata Immich reported. Every field on Asset and on the models it nests is
# read there, and a field removed is a difference the evidence stops noticing.
# Nothing names them on the reading side, so vulture cannot see any of it.
f_number  # unused variable (src/immich_memories/api/models.py)
iso  # unused variable (src/immich_memories/api/models.py)
focal_length  # unused variable (src/immich_memories/api/models.py)
lens_model  # unused variable (src/immich_memories/api/models.py)
objects  # unused variable (src/immich_memories/api/models.py)
device_id  # unused variable (src/immich_memories/api/models.py)
thumbhash  # unused variable (src/immich_memories/api/models.py)
is_trashed  # unused variable (src/immich_memories/api/models.py)
smart_info  # unused variable (src/immich_memories/api/models.py)

# An enum member resolved from the wire value rather than by name: parse_type
# does AssetType(v.upper()), so an Immich asset typed AUDIO round-trips as
# itself instead of collapsing into OTHER.
AUDIO  # unused variable (src/immich_memories/api/models.py)

# Rendered into the prompt the editorial model reads.
# render_person_period_facts does json.dumps(asdict(fact)) and that string is
# spliced into the judge line at film/lines.py:118 via
# with_person_context. The model is the reader; no source line names the keys,
# and dropping one would silently change the cut.
person_token  # unused variable (src/immich_memories/analysis/reading/person_period_facts.py:18)
grounding_moment_ids  # unused variable (src/immich_memories/analysis/reading/person_period_facts.py:25)

# onnxruntime SessionOptions attributes: set on the options object, then read
# by the C++ runtime when InferenceSession is constructed a line or two later
# (triage/encoder.py, analysis/preparation/detectors.py).
_.intra_op_num_threads  # unused attribute (src/immich_memories/triage/encoder.py)
_.inter_op_num_threads  # unused attribute (src/immich_memories/triage/encoder.py)
_.graph_optimization_level  # unused attribute (src/immich_memories/triage/encoder.py)

# Protocol method parameter names on a stub whose body is `...`. A Protocol
# never references its own parameters, which is what trips vulture's
# unused-variable check. The shape mirrors onnxruntime's
# InferenceSession.run(output_names, input_feed), called positionally at :88.
input_feed  # unused variable (src/immich_memories/triage/encoder.py)
output_names  # unused variable (src/immich_memories/triage/encoder.py)

# conn.row_factory = sqlite3.Row -- an sqlite3.Connection attribute the stdlib
# C module reads when it materialises rows.
_.row_factory  # unused attribute (src/immich_memories/operations/store_import.py)

# logging.lastResort, the stdlib module attribute callHandlers falls back to.
# Disabled while LiveDisplayLogHandler owns the terminal, restored afterwards.
_.lastResort  # unused attribute (src/immich_memories/logging_config.py)

# pydantic-settings contract methods, called by the library and never by us.
# get_field_value is abstract on PydanticBaseSettingsSource, so without it the
# source cannot even be instantiated; settings_customise_sources is the hook
# BaseSettings.__init__ calls on every Config() to splice the YAML source in.
_.get_field_value  # unused method (src/immich_memories/config/loader.py)
_.settings_customise_sources  # unused method (src/immich_memories/config/loader.py)

# Reached only from checked-in developer scripts, which vulture does not scan:
# scripts/validate_local_audio.py for the stem check, and
# scripts/verify_hardware_encode.py for the assembly runner.
_.has_full_stems  # unused property (src/immich_memories/audio/music_generator_models.py)
_.run_ffmpeg_assembly  # unused method (src/immich_memories/processing/clip_encoder.py)

# Reported to the owner rather than deleted. Each is either a seam only the
# tests use, or a wiring gap where the missing caller is the defect and removing
# the callee would cement it:
#   complete_run     the only writer of a successful run's LLM spend; the
#                    complete_artifact that replaced it never passes llm_metrics
#   cancel_run       the only writer of status "cancelled", which the CLI filter
#                    and the recovery page still expect to exist
#   validate_image_path  its video/audio twins are used in ~14 places while image
#                    paths are opened unvalidated; a gap, not dead weight
#   response_sha256, unreadable_or_omitted_pages
#                    the episode reader's per-response diagnostics; only tests
#                    read them
#   get_active_display, render_final
#                    the public reads of state production reaches directly; the
#                    tests use them as the window onto it
#   reset_rate_limiter
#                    clears module-global state so tests do not leak into each
#                    other; production never resets it
#   PACK_DIM         read by scripts/triage_heads/semantic_refinement.py, which
#                    vulture does not scan
response_sha256  # unused variable (src/immich_memories/analysis/reading/episode_answers.py)
unreadable_or_omitted_pages  # unused variable (src/immich_memories/analysis/reading/episode_answers.py)
get_active_display  # unused function (src/immich_memories/cli/_helpers.py)
_.render_final  # unused method (src/immich_memories/cli/_live_display.py)
validate_image_path  # unused function (src/immich_memories/security.py)
PACK_DIM  # unused variable (src/immich_memories/triage/encoder.py)
reset_rate_limiter  # unused function (src/immich_memories/web/auth.py)

# Serialized by FastAPI; the Svelte report preview uses this to offer caption opt-in.
has_flagged_photos

# PEP 562: Python calls a module-level __getattr__ for names the module lacks.
# tracking/__init__.py uses it to re-export lazily, so timing spans never load the
# run database (and SQLAlchemy) into the API client and the renderer.
__getattr__  # unused function (src/immich_memories/tracking/__init__.py:43)

# nltk's WordNetCorpusReader calls map_wn from its own constructor; the override in
# free_text/lexicon.py stops it loading a second copy of the corpus. No line here names it.
_.map_wn

# ACE-Step diffusion.py reads this owned handler flag through getattr before
# calling its native decoder; keep compilation disabled on the parked-weight path.
_.mlx_dit_compiled

# StaticMap.render calls this override inside the external staticmap package;
# real HTTP/pixel tests in test_map_tile_layer exercise it on cold and warm frames.
_._draw_base_layer

# RosterFlag.person_urls is read by the Svelte people page across JSON (RosterFlag lives in
# web/roster.py, not the excluded schemas module).
_.person_urls

