import React, { useEffect } from 'react'
import Sidebar    from './components/Sidebar'
import ChatArea   from './components/ChatArea'
import { useStore } from './store'

export default function App() {
  const newChat = useStore(s => s.newChat)
  const chats   = useStore(s => s.chats)

  useEffect(() => {
    if (chats.length === 0) newChat()
  }, [])

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg">
      <Sidebar />
      <ChatArea />
    </div>
  )
}
