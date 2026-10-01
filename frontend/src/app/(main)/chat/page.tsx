import { Suspense } from 'react'
import ChatPage from './components/ChatPage'
import MetaConnectNotice from './components/MetaConnectNotice'

const Page = () => {
  return (
    <>
      {/* Suspense: useSearchParams opts the page into client-side rendering. */}
      <Suspense fallback={null}>
        <MetaConnectNotice />
      </Suspense>
      <ChatPage />
    </>
  )
}

export default Page
