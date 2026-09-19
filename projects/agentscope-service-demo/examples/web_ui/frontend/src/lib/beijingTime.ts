// This deployment's legacy naive timestamps were written by the UTC VM.
export function parseServerTime(value: string): Date {
    return new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(value) ? value : value.replace(' ', 'T') + 'Z');
}
function fullTime(value: string, zone: string): string {
    const date = parseServerTime(value);
    if (Number.isNaN(date.getTime())) return value;
    const parts = new Intl.DateTimeFormat('en-CA', {timeZone: zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(date);
    const p = Object.fromEntries(parts.map(v=>[v.type,v.value]));
    return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}
export const beijingTime = (value:string) => fullTime(value,'Asia/Shanghai');
export const beijingClock = (value:string) => beijingTime(value).slice(11,16);
export const isBeijingToday = (value:string) => beijingTime(value).slice(0,10)===beijingTime(new Date().toISOString()).slice(0,10);
export function sessionDisplayName(name:string|undefined, created?:string):string {
    // Only reinterpret the old automatic UTC title, never arbitrary user names.
    return name && created && name===fullTime(created,'UTC') ? beijingTime(created) : name || '';
}
