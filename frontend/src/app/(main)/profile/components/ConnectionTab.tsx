'use client';

import { useAuth } from '@/contexts/AuthContext';
import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import type React from 'react';
import { useEffect, useState } from 'react';
import ProfileHeader from '@/components/ProfileHeader';
import {
  Avatar,
  Box,
  Divider,
  ScrollArea,
  Text,
  Modal,
  Accordion,
  Tooltip,
} from '@mantine/core';
import PrimaryGlassBtn from '@/components/PrimaryGlassBtn';
import { Plus } from 'lucide-react';
import { useAds } from '@/contexts/AdsContext';
import ConversionTrackingCard from './ConversionTrackingCard';
import MetaReadiness from './MetaReadiness';
import MetaLeads from './MetaLeads';
import MetaLeadDelivery from './MetaLeadDelivery';
import { User, UserOauth } from '@/types/user.dto';
import { notifications } from '@mantine/notifications';
import Pricing from '@/components/subscriptionModals/Pricing';
import {
  useMetaAdsDisconnectConnection,
  useRemoveMetaAdsAccount,
} from '@/hooks/api/useAdsConnectApi';
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Radio,
  Trash2,
  Users,
} from 'lucide-react';
import { formatEndsOn } from '@/lib/subscriptionRows';

// Status-aware — a canceled/past_due subscription must not still read as
// "Subscribed" and unlock the account for publishing or block its removal.
const findActiveSub = (user: User | null | undefined, accountId: string) =>
  user?.subscriptions?.find(
    (sub) =>
      sub.ad_account_id === accountId &&
      (sub.status === 'active' || sub.status === 'trialing')
  );

const hasActiveSub = (user: User | null | undefined, accountId: string) =>
  !!findActiveSub(user, accountId);

interface PlatformItem {
  id: string;
  connection: 'google' | 'meta';
  title: string;
  subtitle: string;
  icon: React.ReactNode;
}
interface ConnectionTabProps {
  onClose?: () => void;
}

const ConnectionTab: React.FC<ConnectionTabProps> = ({ onClose }) => {
  const { connectPlatform } = useAds();
  const { user, updateProfile } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    const connectedPlatform = searchParams.get('connected');
    // The callback no longer puts the access token in the URL, and this used to
    // copy it into a JS-readable `<platform>_ads_token` cookie with a 60-day
    // max-age. Nothing ever read that cookie — it only widened the blast radius
    // of an XSS. Expire any copy still sitting in a browser from before.
    if (connectedPlatform) {
      for (const platform of ['meta', 'google']) {
        document.cookie = `${platform}_ads_token=; path=/; max-age=0; SameSite=Strict`;
      }

      const current = new URLSearchParams(Array.from(searchParams.entries()));
      current.delete('connected');
      current.delete('token');
      const search = current.toString();
      const query = search ? `?${search}` : '';
      router.replace(`${pathname}${query}`);
    }
  }, [searchParams, router, pathname]);

  const data: PlatformItem[] = [
    {
      id: 'id 2',
      connection: 'meta',
      title: 'Meta Ads',
      subtitle:
        'Connect your Facebook account, then choose which ad account to advertise from.',
      icon: (
        <svg
          width="19"
          height="13"
          viewBox="0 0 19 13"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <g clipPath="url(#clip0_6879_14200)">
            <path
              d="M2.05222 8.52496C2.05222 9.26809 2.2115 9.83864 2.41961 10.1838C2.69251 10.6359 3.09945 10.8274 3.51441 10.8274C4.0496 10.8274 4.53922 10.6913 5.48269 9.35468C6.23861 8.28336 7.1293 6.77946 7.72855 5.8367L8.74349 4.23944C9.44849 3.13019 10.2645 1.89709 11.2001 1.06121C11.9638 0.378977 12.7877 0 13.6169 0C15.0091 0 16.3352 0.826374 17.3501 2.37626C18.4608 4.07364 19 6.21164 19 8.41799C19 9.72963 18.7477 10.6934 18.3182 11.4548C17.9032 12.1912 17.0944 12.9269 15.734 12.9269V10.8274C16.8989 10.8274 17.1896 9.73099 17.1896 8.47623C17.1896 6.68816 16.7826 4.70372 15.886 3.28588C15.2497 2.28009 14.4251 1.6656 13.5179 1.6656C12.5367 1.6656 11.7471 2.42355 10.8598 3.77525C10.388 4.49329 9.90368 5.36839 9.35995 6.35578L8.7613 7.44208C7.55873 9.62608 7.25414 10.1235 6.65289 10.9445C5.59899 12.3821 4.69916 12.9269 3.51441 12.9269C2.10907 12.9269 1.2203 12.3035 0.669973 11.3641C0.220652 10.5986 0 9.5943 0 8.44985L2.05222 8.52496Z"
              fill="#0081FB"
            />
            <path
              d="M1.61719 2.52443C2.55813 1.03894 3.91589 0 5.47322 0C6.3752 0 7.27177 0.273456 8.20804 1.0565C9.23211 1.9126 10.3236 3.32237 11.6854 5.64588L12.1738 6.47963C13.3524 8.49113 14.0231 9.52588 14.4155 10.014C14.9204 10.6406 15.2739 10.8274 15.7331 10.8274C16.8979 10.8274 17.1887 9.73099 17.1887 8.47623L18.9991 8.41799C18.9991 9.72963 18.7467 10.6934 18.3172 11.4548C17.9023 12.1912 17.0935 12.9269 15.7331 12.9269C14.8874 12.9269 14.1381 12.7387 13.3095 11.938C12.6726 11.3235 11.928 10.2318 11.3551 9.25045L9.651 6.3348C8.79607 4.87158 8.01173 3.78064 7.55788 3.28649C7.06967 2.75524 6.44193 2.1136 5.44027 2.1136C4.62958 2.1136 3.94105 2.6964 3.36489 3.5877L1.61719 2.52443Z"
              fill="url(#paint0_linear_6879_14200)"
            />
            <path
              d="M5.44112 2.1136C4.63043 2.1136 3.94191 2.6964 3.36575 3.5877C2.55112 4.84725 2.05222 6.72328 2.05222 8.52496C2.05222 9.26809 2.2115 9.83864 2.41961 10.1838L0.669973 11.3641C0.220652 10.5986 0 9.5943 0 8.44985C0 6.36863 0.55768 4.19953 1.61812 2.52443C2.55906 1.03894 3.91682 0 5.47415 0L5.44112 2.1136Z"
              fill="url(#paint1_linear_6879_14200)"
            />
          </g>
          <defs>
            <linearGradient
              id="paint0_linear_6879_14200"
              x1="4.02945"
              y1="7.23051"
              x2="17.0979"
              y2="7.87489"
              gradientUnits="userSpaceOnUse"
            >
              <stop stopColor="#0064E1" />
              <stop offset="0.4" stopColor="#0064E1" />
              <stop offset="0.83" stopColor="#0073EE" />
              <stop offset="1" stopColor="#0082FB" />
            </linearGradient>
            <linearGradient
              id="paint1_linear_6879_14200"
              x1="2.97329"
              y1="9.40745"
              x2="2.97329"
              y2="4.4669"
              gradientUnits="userSpaceOnUse"
            >
              <stop stopColor="#0082FB" />
              <stop offset="1" stopColor="#0064E0" />
            </linearGradient>
            <clipPath id="clip0_6879_14200">
              <rect width="19" height="13" fill="white" />
            </clipPath>
          </defs>
        </svg>
      ),
    },
  ];

  const [, setConnectedPlatforms] = useState<Record<string, boolean>>({});
  const [selectedAccounts, setSelectedAccounts] = useState<
    Record<string, string>
  >({});

  const togglePlatformConnection = (id: string) => {
    setConnectedPlatforms((prev) => ({
      ...prev,
      [id]: !prev[id],
    }));
    connectPlatform('meta');
  };

  // Only reached from the "already subscribed" branch of the row click, so this
  // account is paid for and there is nothing to assign — just make it the
  // selected one. (This used to probe "does ANY sub have ANY account", which is
  // account-blind, behind an unreachable "subscribe first" alert.)
  const handleSubscriptionLogic = async (id: string) => {
    try {
      await updateProfile({ select_meta_id: id });
    } catch (error: unknown) {
      if (error instanceof Error) {
        notifications.show({
          title: 'Error',
          message: error.message,
          color: 'red',
          autoClose: 5000,
        });
      }
    }
  };
  return (
    <Box className="text-primary-text flex h-full w-full flex-col overflow-hidden">
      <Box className="text-primary-text flex w-full shrink-0 flex-col">
        {/* Header with Title and Close Button */}
        <ProfileHeader name="Connections" onClose={onClose} />
        <Box className="border-primary-text/6 border-t" />
      </Box>
      {/* body */}
      <ScrollArea
        className="flex-1"
        scrollbars="y"
        type="hover"
        scrollbarSize={6}
      >
        <Box className="flex flex-col gap-5 p-4 sm:px-7! sm:py-6!">
          <Box>
            <Text fz={13} fw={400} className="text-[#FAF9F573]">
              Link ad platforms and manage which account is active.
            </Text>
          </Box>
          {data.length === 0 ? (
            <Box className="flex items-center justify-center">
              <Text className="text-sm font-medium text-white">
                No connected platforms found.
              </Text>
            </Box>
          ) : (
            data.map((item) => {
              const platformTokens =
                user?.oauth_tokens?.filter(
                  (t) => t.platform === item.connection
                ) || [];
              const isConnected = platformTokens.length > 0;
              const allAccounts = platformTokens.flatMap(
                (t) => t.accessible_accounts || []
              );

              // The selected account is whatever the server says it is — nothing
              // else. This used to fall back to "the first subscribed account",
              // painting a green Active badge on an account the backend was NOT
              // publishing into, while the radio dot (which reads select_meta_id)
              // sat on a different one. Whether the selected account is also PAID
              // is decided per row below, so a canceled sub reads "Not Subscribed"
              // instead of quietly moving the marker.
              const activeAccountId: string | undefined =
                selectedAccounts[item.id] ??
                (item.connection === 'meta' ? user?.select_meta_id : undefined);

              return (
                <ConnectionPlatforms
                  item={item}
                  isConnected={isConnected}
                  activeAccountId={activeAccountId}
                  setSelectedAccounts={setSelectedAccounts}
                  togglePlatformConnection={togglePlatformConnection}
                  key={item.id}
                  platformTokens={platformTokens}
                  allAccounts={allAccounts}
                  user={user}
                  handleSubscriptionLogic={handleSubscriptionLogic}
                />
              );
            })
          )}
        </Box>
      </ScrollArea>
    </Box>
  );
};

export default ConnectionTab;

const ConnectionPlatforms = ({
  item,
  isConnected,
  activeAccountId,
  togglePlatformConnection,
  platformTokens,
  user,
  handleSubscriptionLogic,
}: {
  item: PlatformItem;
  isConnected: boolean;
  activeAccountId: string | undefined | null;
  setSelectedAccounts: React.Dispatch<
    React.SetStateAction<Record<string, string>>
  >;
  togglePlatformConnection: (id: string) => void;
  platformTokens: UserOauth[];
  allAccounts: { id: string; name: string }[];
  user: User | null;
  handleSubscriptionLogic: (id: string, type: string) => void;
}) => {
  const [subModalOpened, setSubModalOpened] = useState(false);
  const [pendingAccountId, setPendingAccountId] = useState<string | null>(null);

  const { updateProfile } = useAuth();
  const { mutateAsync: disconnectConnection, isPending: isDisconnecting } =
    useMetaAdsDisconnectConnection();
  const [disconnectModalOpened, setDisconnectModalOpened] = useState(false);
  const [connectionToDisconnect, setConnectionToDisconnect] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const { mutateAsync: removeAdAccount, isPending: isRemovingAccount } =
    useRemoveMetaAdsAccount();
  const [removeModalOpened, setRemoveModalOpened] = useState(false);
  const [accountToRemove, setAccountToRemove] = useState<{
    id: string;
    name: string;
  } | null>(null);

  // Meta tool modal state
  const [activeMetaModal, setActiveMetaModal] = useState<
    'readiness' | 'delivery' | 'leads' | 'tracking' | null
  >(null);

  const metaModalStyles = {
    content: {
      backgroundColor: '#111111',
      border: '1px solid #FFFFFF14',
      borderRadius: '16px',
      color: 'white',
      boxShadow: '0 24px 60px rgba(0, 0, 0, 0.85)',
    },
    header: {
      backgroundColor: 'transparent',
      borderBottom: '1px solid #FFFFFF14',
      padding: '16px 20px',
    },
    title: {
      fontWeight: 600,
      color: 'white',
      fontSize: '15px',
    },
    body: {
      padding: '20px',
    },
    close: {
      color: '#A1A1AA',
      '&:hover': {
        backgroundColor: '#FFFFFF14',
        color: 'white',
      },
    },
  };

  const handleDisconnect = async () => {
    if (!connectionToDisconnect) return;
    try {
      await disconnectConnection(connectionToDisconnect.id);
      notifications.show({
        title: 'Success',
        message: 'Connection disconnected successfully',
        color: 'green',
      });
      await updateProfile();
    } catch (error) {
      notifications.show({
        title: 'Error',
        message:
          error instanceof Error
            ? error.message
            : 'Failed to disconnect connection',
        color: 'red',
      });
    } finally {
      setDisconnectModalOpened(false);
      setConnectionToDisconnect(null);
    }
  };

  const handleRemoveAccount = async () => {
    if (!accountToRemove) return;
    try {
      await removeAdAccount(accountToRemove.id);
      notifications.show({
        title: 'Success',
        message: 'Ad account removed successfully',
        color: 'green',
      });
      await updateProfile();
    } catch (error) {
      notifications.show({
        title: 'Error',
        message:
          error instanceof Error
            ? error.message
            : 'Failed to remove ad account',
        color: 'red',
      });
    } finally {
      setRemoveModalOpened(false);
      setAccountToRemove(null);
    }
  };

  return (
    <Box key={item.id}>
      <Modal
        opened={subModalOpened}
        onClose={() => {
          setSubModalOpened(false);
          setPendingAccountId(null);
        }}
        withCloseButton={false}
        centered
        size="auto"
        padding={0}
        radius={28}
        zIndex={9999999999999}
        overlayProps={{
          backgroundOpacity: 0.75,
          blur: 8,
          color: '#000000',
        }}
        styles={{
          overlay: {
            background: 'rgba(0, 0, 0, 0.75)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
          },
          content: { background: 'transparent', boxShadow: 'none', overflow: 'visible' },
          body: { padding: 0, overflow: 'visible' },
        }}
      >
        <Pricing
          onClose={() => {
            setSubModalOpened(false);
            setPendingAccountId(null);
          }}
          pendingAccountId={pendingAccountId}
        />
      </Modal>

      {/* Disconnect Modal */}
      <Modal
        opened={disconnectModalOpened}
        onClose={() => setDisconnectModalOpened(false)}
        title="Disconnect Connection"
        centered
        styles={{
          content: {
            backgroundColor: '#111111',
            border: '1px solid #FFFFFF14',
            borderRadius: '16px',
            color: 'white',
          },
          header: {
            backgroundColor: 'transparent',
            borderBottom: '1px solid #FFFFFF14',
          },
          title: {
            fontWeight: 600,
            color: 'white',
          },
          close: {
            color: '#A1A1AA',
            '&:hover': {
              backgroundColor: '#FFFFFF14',
              color: 'white',
            },
          },
        }}
        zIndex={999999999999999}
      >
        <Box className="flex flex-col gap-4">
          <Text size="sm" c="dimmed">
            Are you sure you want to disconnect{' '}
            <strong>{connectionToDisconnect?.name}</strong>? This will remove
            the entire connection and its ad accounts.
          </Text>
          <Box className="mt-4 flex justify-end gap-3">
            <PrimaryGlassBtn
              onClick={() => setDisconnectModalOpened(false)}
              px={16}
              py={8}
            >
              Cancel
            </PrimaryGlassBtn>
            <button
              onClick={handleDisconnect}
              disabled={isDisconnecting}
              className="flex items-center gap-2 rounded-lg bg-red-500/10 px-4 py-2 text-sm font-medium text-red-500 transition-colors hover:bg-red-500/20 disabled:opacity-50"
            >
              {isDisconnecting ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Trash2 size={16} />
              )}
              Disconnect
            </button>
          </Box>
        </Box>
      </Modal>

      {/* Remove single ad account modal */}
      <Modal
        opened={removeModalOpened}
        onClose={() => setRemoveModalOpened(false)}
        title="Remove Ad Account"
        centered
        styles={{
          content: {
            backgroundColor: '#111111',
            border: '1px solid #FFFFFF14',
            borderRadius: '16px',
            color: 'white',
          },
          header: {
            backgroundColor: 'transparent',
            borderBottom: '1px solid #FFFFFF14',
          },
          title: {
            fontWeight: 600,
            color: 'white',
          },
          close: {
            color: '#A1A1AA',
            '&:hover': {
              backgroundColor: '#FFFFFF14',
              color: 'white',
            },
          },
        }}
        zIndex={999999999999999}
      >
        <Box className="flex flex-col gap-4">
          <Text size="sm" c="dimmed">
            Are you sure you want to remove{' '}
            <strong>{accountToRemove?.name}</strong>? Its tracking setup (pixel,
            lead routing) will need to be reconfigured if you reconnect it
            later.
          </Text>
          <Box className="mt-4 flex justify-end gap-3">
            <PrimaryGlassBtn
              onClick={() => setRemoveModalOpened(false)}
              px={16}
              py={8}
            >
              Cancel
            </PrimaryGlassBtn>
            <button
              onClick={handleRemoveAccount}
              disabled={isRemovingAccount}
              className="flex items-center gap-2 rounded-lg bg-red-500/10 px-4 py-2 text-sm font-medium text-red-500 transition-colors hover:bg-red-500/20 disabled:opacity-50"
            >
              {isRemovingAccount ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Trash2 size={16} />
              )}
              Remove
            </button>
          </Box>
        </Box>
      </Modal>

      {/* Meta Readiness Modal */}
      <Modal
        opened={activeMetaModal === 'readiness'}
        onClose={() => setActiveMetaModal(null)}
        title="Account Readiness & Checklist"
        centered
        size="lg"
        zIndex={100200}
        styles={metaModalStyles}
        overlayProps={{ backgroundOpacity: 0.7, blur: 4 }}
      >
        <Box className="max-h-[72vh] overflow-y-auto pr-1">
          <MetaReadiness />
        </Box>
      </Modal>

      {/* Meta Lead Delivery Modal */}
      <Modal
        opened={activeMetaModal === 'delivery'}
        onClose={() => setActiveMetaModal(null)}
        title="Lead Delivery & Routing"
        centered
        size="lg"
        zIndex={100200}
        styles={metaModalStyles}
        overlayProps={{ backgroundOpacity: 0.7, blur: 4 }}
      >
        <Box className="max-h-[72vh] overflow-y-auto pr-1">
          <MetaLeadDelivery />
        </Box>
      </Modal>

      {/* Meta Instant Leads Modal */}
      <Modal
        opened={activeMetaModal === 'leads'}
        onClose={() => setActiveMetaModal(null)}
        title="Instant Form Leads"
        centered
        size="xl"
        zIndex={100200}
        styles={metaModalStyles}
        overlayProps={{ backgroundOpacity: 0.7, blur: 4 }}
      >
        <Box className="max-h-[72vh] overflow-y-auto pr-1">
          <MetaLeads />
        </Box>
      </Modal>

      {/* Meta Conversion Tracking Modal */}
      <Modal
        opened={activeMetaModal === 'tracking'}
        onClose={() => setActiveMetaModal(null)}
        title="Conversion Tracking Setup"
        centered
        size="lg"
        zIndex={100200}
        styles={metaModalStyles}
        overlayProps={{ backgroundOpacity: 0.7, blur: 4 }}
      >
        <Box className="max-h-[72vh] overflow-y-auto pr-1">
          <ConversionTrackingCard className="flex flex-col gap-2" />
        </Box>
      </Modal>

      <Box className="flex flex-col rounded-[14px] border border-[#FFFFFF14] bg-[#FFFFFF05] pb-4">
        <Box className="flex flex-col justify-between gap-3 px-4 pt-4 sm:flex-row sm:items-center">
          <Box className="flex min-w-0 flex-1 items-start gap-3.5">
            {/* icon */}
            <Box className="flex h-10 max-h-10 min-h-10 w-10 max-w-10 min-w-10 shrink-0 items-center justify-center rounded-xl border border-[#FFFFFF1A] bg-[#FFFFFF12]">
              {item.icon}
            </Box>
            {/* title & subtitle */}
            <Box className="min-w-0 flex-1 flex-col">
              <Text fz={14} fw={600} className="text-primary-text">
                {item.title}
              </Text>
              <Text
                fz={12}
                fw={400}
                className="text-secondary-text/60 line-clamp-2"
              >
                {item.subtitle}
              </Text>
              {isConnected && (
                <Box className="flex items-center justify-start pt-[7.5px] text-[#22C55E]">
                  <span className="mr-1 h-1.5 w-1.5 animate-pulse rounded-full bg-[#22C55E]" />
                  <Text fz={11} fw={500}>
                    Connected
                  </Text>
                </Box>
              )}
            </Box>
          </Box>
          {/* button */}
          <Box className="shrink-0 self-end sm:self-center">
            <PrimaryGlassBtn
              onClick={() => togglePlatformConnection(item.id)}
              px={14}
              py={8}
            >
              {isConnected ? (
                <>
                  <Plus className="mr-1" size={14} />
                  Add Account
                </>
              ) : (
                <>
                  <Plus className="mr-1" size={14} />
                  Connect
                </>
              )}
            </PrimaryGlassBtn>
          </Box>
        </Box>
        {isConnected && <Divider className="my-3" />}

        {isConnected && (
          <div className="px-4 pt-2 pb-4">
            <Accordion
              variant="separated"
              multiple
              defaultValue={
                platformTokens[0] ? [platformTokens[0].id || '0'] : []
              }
            >
              {platformTokens.map((account: UserOauth, index) => {
                const accountAdAccounts = (account.accessible_accounts ||
                  []) as { id: string; name: string }[];
                const hasAccounts = accountAdAccounts.length > 0;
                return (
                  <Accordion.Item
                    key={`${account.id || ''}-${index}`}
                    value={account.id || index.toString()}
                    className="mb-4 overflow-hidden rounded-xl border border-[#FFFFFF14] bg-[#FFFFFF05]"
                  >
                    <Accordion.Control className="cursor-pointer hover:bg-[#FFFFFF0A]">
                      <Box className="flex w-full items-center justify-between">
                        <Box className="flex items-center gap-4">
                          <Avatar
                            src={account.meta_user_image}
                            size={42}
                            radius="xl"
                            color="blue"
                          >
                            {account.meta_user_name
                              ?.substring(0, 2)
                              .toUpperCase()}
                          </Avatar>
                          <Box>
                            <Text fw={500} size="sm" c="white">
                              {account.meta_user_name}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {hasAccounts
                                ? `${accountAdAccounts.length} ad accounts`
                                : 'No ad accounts'}
                            </Text>
                          </Box>
                        </Box>

                        <Box
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setConnectionToDisconnect({
                              id: account.id,
                              name: account.meta_user_name || 'Account',
                            });
                            setDisconnectModalOpened(true);
                          }}
                          className="mr-4 flex cursor-pointer items-center justify-center rounded-lg p-2 text-[#FAF9F54D] transition-colors hover:bg-red-500/10 hover:text-red-500"
                        >
                          <Trash2 size={18} />
                        </Box>
                      </Box>
                    </Accordion.Control>
                    <Accordion.Panel className="border-t border-[#FFFFFF14]">
                      <Box className="flex flex-col py-2">
                        {!hasAccounts ? (
                          <Box className="py-4">
                            <Text size="xs" c="dimmed" ta="center">
                              No ad accounts yet — add one from this Facebook
                              account to start advertising.
                            </Text>
                          </Box>
                        ) : (
                          accountAdAccounts.map((acc, accIndex) => {
                            const isSelected = activeAccountId === acc.id;

                            // Status-aware — a canceled/past_due subscription
                            // must not still read as "Subscribed" and unlock
                            // the account.
                            const isInSubscribe = hasActiveSub(user, acc.id);

                            // "Active" = the account Punk builds into AND has a
                            // live subscription. A selected but unpaid account
                            // keeps its radio marker and reads "Not Subscribed".
                            const isActive = isSelected && isInSubscribe;

                            return (
                              <Box
                                key={`${acc.id || ''}-${accIndex}`}
                                onClick={() => {
                                  if (isInSubscribe) {
                                    handleSubscriptionLogic(
                                      acc.id,
                                      'ad_account_id'
                                    );
                                  } else {
                                    setPendingAccountId(acc.id);
                                    setSubModalOpened(true);
                                  }
                                }}
                                className="flex cursor-pointer flex-wrap items-center justify-between gap-2 rounded-lg px-3 py-2.5 transition-colors hover:bg-[#FFFFFF0A] sm:flex-nowrap"
                              >
                                <Box className="flex min-w-0 flex-1 items-center gap-3">
                                  {/* Radio Circle */}
                                  <Box
                                    className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full transition-all ${
                                      isSelected
                                        ? 'border-2 border-white bg-transparent'
                                        : 'border border-[#FFFFFF33] bg-transparent'
                                    }`}
                                  >
                                    {isSelected && (
                                      <Box className="h-1.5 w-1.5 rounded-full bg-white" />
                                    )}
                                  </Box>
                                  {/* Account details */}
                                  <Box className="flex min-w-0 flex-1 flex-col">
                                    <Text
                                      fz={13}
                                      fw={500}
                                      className="text-primary-text truncate leading-tight"
                                    >
                                      {acc.name}
                                    </Text>
                                    <Text
                                      fz={11}
                                      fw={400}
                                      className="mt-0.5 truncate leading-tight text-[#FAF9F54D]"
                                    >
                                      {acc.id}
                                    </Text>
                                  </Box>
                                </Box>
                                {/* Active / Subscribe Badge */}
                                <Box className="flex shrink-0 items-center gap-2">
                                  {isActive ? (
                                    <Box className="shrink-0 rounded-full bg-[#22C55E1A] px-2.5 py-0.5">
                                      <Text
                                        fz={11}
                                        fw={500}
                                        className="text-[#22C55E]"
                                      >
                                        Active
                                      </Text>
                                    </Box>
                                  ) : isInSubscribe ? (
                                    <Box className="shrink-0 rounded-full bg-[#3B82F61A] px-2.5 py-0.5">
                                      <Text
                                        fz={11}
                                        fw={500}
                                        className="text-[#3B82F6]"
                                      >
                                        Subscribed
                                      </Text>
                                    </Box>
                                  ) : (
                                    <Box className="shrink-0 rounded-full bg-[#F443361A] px-2.5 py-0.5">
                                      <Text
                                        fz={11}
                                        fw={500}
                                        className="text-[#F44336]"
                                      >
                                        Not Subscribed
                                      </Text>
                                    </Box>
                                  )}
                                  <Tooltip
                                    label={
                                      isInSubscribe
                                        ? // Removal stays blocked until the paid period
                                          // ends, even after a cancel — say so instead of
                                          // asking the user to cancel what they cancelled.
                                          findActiveSub(user, acc.id)
                                            ?.cancel_at_period_end
                                          ? `Subscription runs until ${formatEndsOn(
                                              findActiveSub(user, acc.id)
                                                ?.current_period_end
                                            )}. You can remove this account after.`
                                          : 'Cancel the subscription for this ad account before removing it'
                                        : 'Remove ad account'
                                    }
                                  >
                                    <Box
                                      onClick={(e) => {
                                        e.preventDefault();
                                        e.stopPropagation();
                                        if (isInSubscribe) return;
                                        setAccountToRemove({
                                          id: acc.id,
                                          name: acc.name,
                                        });
                                        setRemoveModalOpened(true);
                                      }}
                                      className={`flex items-center justify-center rounded-lg p-1.5 transition-colors ${
                                        isInSubscribe
                                          ? 'cursor-not-allowed text-[#FAF9F51F]'
                                          : 'cursor-pointer text-[#FAF9F54D] hover:bg-red-500/10 hover:text-red-500'
                                      }`}
                                    >
                                      <Trash2 size={14} />
                                    </Box>
                                  </Tooltip>
                                </Box>
                              </Box>
                            );
                          })
                        )}
                      </Box>
                    </Accordion.Panel>
                  </Accordion.Item>
                );
              })}
            </Accordion>
          </div>
        )}
        {/* Meta setup, tracking & lead management tools opened in dedicated modals */}
        {isConnected && item.connection === 'meta' && (
          <Box className="border-t border-[#FFFFFF14] px-4 pt-3.5 pb-1">
            <Text
              fw={600}
              fz={11}
              className="mb-2.5! tracking-wider text-[#FAF9F566] uppercase"
            >
              Meta Tools & Management
            </Text>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => setActiveMetaModal('readiness')}
                className="group flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-[#FFFFFF14] bg-[#FFFFFF05] p-3 text-left transition-all hover:border-[#FFFFFF26] hover:bg-[#FFFFFF0C]"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-500/10 text-emerald-400">
                    <CheckCircle2 size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Text
                      fz={12}
                      fw={600}
                      className="text-primary-text truncate group-hover:text-white"
                    >
                      Account Readiness
                    </Text>
                    <Text fz={11} className="truncate text-[#FAF9F54D]">
                      Setup checklist & prerequisites
                    </Text>
                  </div>
                </div>
                <ChevronRight
                  size={15}
                  className="shrink-0 text-[#FAF9F533] transition-transform group-hover:translate-x-0.5 group-hover:text-white"
                />
              </button>

              <button
                type="button"
                onClick={() => setActiveMetaModal('delivery')}
                className="group flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-[#FFFFFF14] bg-[#FFFFFF05] p-3 text-left transition-all hover:border-[#FFFFFF26] hover:bg-[#FFFFFF0C]"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-blue-500/20 bg-blue-500/10 text-blue-400">
                    <Radio size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Text
                      fz={12}
                      fw={600}
                      className="text-primary-text truncate group-hover:text-white"
                    >
                      Lead Delivery
                    </Text>
                    <Text fz={11} className="truncate text-[#FAF9F54D]">
                      Page webhook routing & status
                    </Text>
                  </div>
                </div>
                <ChevronRight
                  size={15}
                  className="shrink-0 text-[#FAF9F533] transition-transform group-hover:translate-x-0.5 group-hover:text-white"
                />
              </button>

              <button
                type="button"
                onClick={() => setActiveMetaModal('leads')}
                className="group flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-[#FFFFFF14] bg-[#FFFFFF05] p-3 text-left transition-all hover:border-[#FFFFFF26] hover:bg-[#FFFFFF0C]"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-purple-500/20 bg-purple-500/10 text-purple-400">
                    <Users size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Text
                      fz={12}
                      fw={600}
                      className="text-primary-text truncate group-hover:text-white"
                    >
                      Instant Form Leads
                    </Text>
                    <Text fz={11} className="truncate text-[#FAF9F54D]">
                      Inspect submitted lead records
                    </Text>
                  </div>
                </div>
                <ChevronRight
                  size={15}
                  className="shrink-0 text-[#FAF9F533] transition-transform group-hover:translate-x-0.5 group-hover:text-white"
                />
              </button>

              <button
                type="button"
                onClick={() => setActiveMetaModal('tracking')}
                className="group flex cursor-pointer items-center justify-between gap-3 rounded-xl border border-[#FFFFFF14] bg-[#FFFFFF05] p-3 text-left transition-all hover:border-[#FFFFFF26] hover:bg-[#FFFFFF0C]"
              >
                <div className="flex min-w-0 items-center gap-2.5">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-amber-500/20 bg-amber-500/10 text-amber-400">
                    <Activity size={16} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Text
                      fz={12}
                      fw={600}
                      className="text-primary-text truncate group-hover:text-white"
                    >
                      Conversion Tracking
                    </Text>
                    <Text fz={11} className="truncate text-[#FAF9F54D]">
                      Pixel, CAPI & datasets
                    </Text>
                  </div>
                </div>
                <ChevronRight
                  size={15}
                  className="shrink-0 text-[#FAF9F533] transition-transform group-hover:translate-x-0.5 group-hover:text-white"
                />
              </button>
            </div>
          </Box>
        )}
      </Box>
    </Box>
  );
};
