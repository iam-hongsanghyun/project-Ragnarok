/**
 * Jest setup — primes the live-binding constants under
 * `lib/constants/` with the captured fixtures BEFORE any test file's
 * module body runs.
 *
 * Production-time code path:
 *
 *   index.tsx → <ConfigBootstrap> → GET /api/config → applyConfigBundle
 *                                                  → applyStandardTypesBundle
 *
 * In Jest there is no backend, so the same setters are called here with
 * checked-in fixture data instead. See
 * `lib/constants/__fixtures__/README.md` for how to refresh.
 */
import schemaFixture from 'lib/constants/__fixtures__/pypsa_schema.fixture.json';
import standardTypesFixture from 'lib/constants/__fixtures__/pypsa_standard_types.fixture.json';

import { applyConfigBundle } from 'lib/constants/pypsa_schema';
import { applyStandardTypesBundle } from 'lib/constants/pypsa_standard_types';

applyConfigBundle(
  // The fixture shape matches the PypsaSchemaFile contract; we cast
  // because the JSON import is typed broadly.
  schemaFixture as unknown as Parameters<typeof applyConfigBundle>[0],
  // network_import_policy isn't in the schema fixture — load tests that
  // need it can override; default to empty.
  { fields: [] },
);
applyStandardTypesBundle(
  standardTypesFixture as unknown as Parameters<typeof applyStandardTypesBundle>[0],
);
