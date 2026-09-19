import assert from 'node:assert/strict';
import {beijingClock,beijingTime,sessionDisplayName} from './src/lib/beijingTime.ts';
assert.equal(beijingClock('2026-09-14T06:50:52'),'14:50');
assert.equal(beijingTime('2026-09-14T20:00:00Z'),'2026-09-15 04:00:00');
assert.equal(beijingClock('2026-09-14T14:50:52+08:00'),'14:50');
assert.equal(sessionDisplayName('888','2026-09-14T06:50:52'),'888');
assert.equal(sessionDisplayName('2026-09-14 06:50:52','2026-09-14T06:50:52'),'2026-09-14 14:50:52');
console.log('PASS Beijing conversion, midnight boundary, offset input and custom names');
