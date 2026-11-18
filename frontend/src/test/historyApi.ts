// The history methods of ApiClient for fake clients in tests that don't care about history:
// spread `...noHistory` into the fake. The list is empty, so a start with no stored session
// creates a new one, as before step 45.
import type { ApiClient } from '@/api/client'

export const noHistory: Pick<ApiClient, 'listSessions' | 'renameSession' | 'deleteSession'> = {
  listSessions: async () => [],
  renameSession: async () => {
    throw new Error('renameSession is not used here')
  },
  deleteSession: async () => {
    throw new Error('deleteSession is not used here')
  },
}
