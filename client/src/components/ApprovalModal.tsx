import React from 'react'
import { useCeresStore } from '../store/useCeresStore'

export const ApprovalModal: React.FC = () => {
  const { pendingApproval, approveAction } = useCeresStore()

  if (!pendingApproval) return null

  const handleAction = async (action: 'approve' | 'deny') => {
    try { 
      await approveAction(action)
    } catch (e) {
      console.error('Error sending approval:', e)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-gray-900 border border-gray-700 rounded-lg shadow-xl p-6">
        <div className="flex items-center space-x-3 mb-4 text-amber-500">
          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path></svg>
          <h2 className="text-xl font-semibold text-white">Action Required</h2>
        </div>
        
        <p className="text-gray-300 mb-4">{pendingApproval.message}</p>
        
        <div className="bg-gray-800 rounded p-4 mb-6 max-h-48 overflow-y-auto font-mono text-sm text-gray-300">
          <pre>{JSON.stringify(pendingApproval.action, null, 2)}</pre>
        </div>
        
        <div className="flex justify-end space-x-3">
          <button 
            onClick={() => handleAction('deny')}
            className="px-4 py-2 rounded font-medium text-white bg-gray-700 hover:bg-gray-600 transition-colors"
          >
            Deny Action
          </button>
          <button 
            onClick={() => handleAction('approve')}
            className="px-4 py-2 rounded font-medium text-white bg-red-600 hover:bg-red-500 transition-colors shadow-lg shadow-red-500/20"
          >
            Approve & Execute
          </button>
        </div>
      </div>
    </div>
  )
}
