# Test fixtures

Snapshots of the PyPSA schema + standard-types catalogues, captured from
the live backend builder (`backend/app/pypsa_schema_builder.py`) at
commit time. **For Jest only.** Production code fetches the same shape
from `GET /api/config` at app boot — see `lib/api/config.ts` and the
`<ConfigBootstrap>` wrapper in `src/index.tsx`.

To refresh after a PyPSA upgrade:

```bash
.venv-pypsa/bin/python -c "
import json
from backend.app.pypsa_schema_builder import build_pypsa_schema, build_standard_types
out = 'frontend/Ragnarok_default/src/lib/constants/__fixtures__'
with open(out + '/pypsa_schema.fixture.json', 'w') as f:
    json.dump(build_pypsa_schema(), f, indent=2)
with open(out + '/pypsa_standard_types.fixture.json', 'w') as f:
    json.dump(build_standard_types(), f, indent=2)
"
```

These files are NOT imported by production code. The live bindings in
`lib/constants/pypsa_schema.ts` and `pypsa_standard_types.ts` start
empty in production; they're populated by the boot fetch.
