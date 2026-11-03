// URL params that set the initial UI state, so screenshots of any view are reproducible:
//   ?tab=map&day=2   ?tab=book&confirm=flight   ?why=F   ?picker=1   ?history=1
const params = new URLSearchParams(window.location.search)

export const demo = {
  tab: params.get('tab'),
  day: params.get('day'),
  confirm: params.get('confirm'),
  why: params.get('why'),
  picker: params.has('picker'),
  history: params.has('history'),
}
