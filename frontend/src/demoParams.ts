// URL params that set the initial UI state, so screenshots of any view are reproducible.
// ?demo=1 loads the San Jose fixture trip instead of a backend session; the others pick a view:
//   ?demo=1&tab=map&day=2   ?demo=1&tab=book&confirm=flight   ?demo=1&why=F   ?demo=1&picker=1   ?history=1
const params = new URLSearchParams(window.location.search)

export const demo = {
  enabled: params.has('demo'),
  tab: params.get('tab'),
  day: params.get('day'),
  confirm: params.get('confirm'),
  why: params.get('why'),
  picker: params.has('picker'),
  history: params.has('history'),
}
