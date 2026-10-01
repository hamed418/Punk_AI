import CampaignDetail from '../components/CampaignDetail'

interface CampaignDetailPageProps {
  params: Promise<{
    threadId: string
  }>
}

const CampaignDetailPage = async ({ params }: CampaignDetailPageProps) => {
  const { threadId } = await params

  return <CampaignDetail threadId={threadId} />
}

export default CampaignDetailPage
