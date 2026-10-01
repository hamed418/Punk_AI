import { WidgetLayout } from '@/app/(main)/chat/components';
import { Box, Skeleton } from '@mantine/core';

interface SingleWidgetSkeletonProps {
  showLogo?: boolean;
}

const SingleWidgetSkeleton = ({}: SingleWidgetSkeletonProps) => {
  return (
    <WidgetLayout
      mode="single"
      className="pointer-events-none mx-auto w-full max-w-207.5"
    >
      <Box className="relative rounded-[30px]">
        <Box
          className="border-stroke-widget bg-primary-widget! shadow-widget! light:shadow-lg! w-full rounded-[30px] border"
          style={{
            backdropFilter: 'blur(75.9px)',
          }}
        >
          {/* Header */}
          <Box className="border-underline/15 flex w-full items-center justify-between border-b px-5 pt-5 pb-4">
            <Box className="flex min-w-0 items-center gap-2">
              {/* Icon Container */}
              <Box
                className="bg-primary-text/7 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                style={{
                  boxShadow: `
                    inset -3px -5px 2.5px -5px #FFFFFF,
                    inset 2.5px 3.5px 2px -3.5px #FFFFFF
                  `,
                }}
              >
                <Skeleton circle h={14} w={14} />
              </Box>
              {/* Title & Subtitle Skeleton */}
              <Box className="ml-1 flex min-w-0 flex-col gap-1.5">
                <Skeleton h={15} w={140} radius="sm" />
                <Skeleton h={11} w={210} radius="sm" />
              </Box>
            </Box>
            <Skeleton h={10} w={10} />
          </Box>

          {/* Options */}
          <Box className="px-5 py-1">
            {[0, 1, 2].map((idx) => (
              <Box
                key={idx}
                className="border-underline/15 border-t py-1 transition-all duration-200 first:border-0"
              >
                <Box className="flex items-center justify-between rounded-full p-1">
                  <Box className="flex items-center gap-3">
                    {/* Circle Number Skeleton */}
                    <Skeleton circle h={32} w={32} className="shrink-0" />
                    {/* Label & Description Skeleton */}
                    <Box className="flex items-center gap-1.5">
                      <Skeleton
                        h={13}
                        w={idx === 0 ? 85 : idx === 1 ? 110 : 70}
                        radius="sm"
                      />
                      <Skeleton
                        h={13}
                        w={idx === 0 ? 210 : idx === 1 ? 150 : 240}
                        radius="sm"
                      />
                    </Box>
                  </Box>
                </Box>
              </Box>
            ))}
          </Box>

          {/* Custom Input Option */}
          <Box className="border-underline/15 flex items-center gap-2 border-t px-5 py-3 transition-all duration-200">
            <Box className="bg-primary-widget flex h-8 w-8 shrink-0 items-center justify-center rounded-full">
              <Skeleton h={14} w={14} circle />
            </Box>
            <Skeleton h={14} w={150} radius="sm" />
          </Box>
        </Box>
      </Box>
    </WidgetLayout>
  );
};

export default SingleWidgetSkeleton;
