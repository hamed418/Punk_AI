'use client';

import { Box, Skeleton } from '@mantine/core';

export default function MapWidgetSkeleton() {
  return (
    <Box className="mx-auto flex w-full max-w-207.5 flex-col gap-1.5">
      <Box className="space-y-2">
        <Skeleton
          height={15}
          w={{ base: 312, sm: 512, md: 712 }}
          className="rounded-sm!"
        />
        <Skeleton
          height={15}
          w={{ base: 192, sm: 212, md: 412 }}
          className="rounded-sm!"
        />
      </Box>
      <Box className="border-stroke-widget light:border-[#00000033] relative h-[64dvh] w-full max-w-207.5 overflow-hidden rounded-lg border-2 md:h-150 lg:h-[64dvh] xl:h-[68dvh] 2xl:h-140">
        <Box className="absolute inset-0 animate-pulse bg-[#1a2535]" />

        <Box className="absolute top-3 left-3 overflow-hidden">
          <Skeleton
            height={40}
            className="rounded-md! shadow-lg! sm:rounded-xl!"
            w={{ base: 40, sm: 220 }}
          />
        </Box>

        <Box className="absolute right-3 bottom-3 flex flex-col gap-1.5">
          <Skeleton className="shadow-md" height={40} width={40} />
          <Skeleton className="shadow-md" height={40} width={40} />
        </Box>

        <Box className="absolute bottom-4 left-3">
          <Skeleton className="shadow-md" height={30} width={30} />
        </Box>

        <Box
          className="shadow-widget absolute top-2 right-2 z-10 flex origin-top-right scale-72 flex-col overflow-hidden rounded-3xl md:scale-100 lg:scale-68 xl:scale-100"
          style={{
            width: 320,
            background: 'var(--color-primary-bg, #0d1520)',
            backdropFilter: 'blur(40px)',
            WebkitBackdropFilter: 'blur(40px)',
          }}
        >
          <Box className="flex items-center gap-3 px-4 py-3">
            <Skeleton circle height={36} width={36} className="shrink-0" />
            <Box className="flex flex-1 flex-col gap-1.5">
              <Skeleton height={14} radius="sm" width="65%" />
              <Skeleton height={10} radius="sm" width="80%" />
            </Box>
            <Skeleton circle height={22} width={22} className="shrink-0" />
          </Box>

          <Box className="flex flex-col gap-3 px-3 pb-4">
            <Box className="flex items-center gap-3 rounded-xl bg-white/5 px-4 py-3.5">
              <Skeleton height={32} radius="sm" width="45%" />
              <Skeleton height={16} radius="sm" width="40%" />
            </Box>

            <Box className="px-1">
              <Skeleton height={14} radius="sm" width="55%" />
            </Box>

            <Box className="flex flex-col overflow-hidden rounded-xl bg-white/5">
              {[0, 1, 2].map((i) => (
                <Box
                  key={i}
                  className="flex items-center justify-between gap-2 border-b border-white/6 px-3 py-3 last:border-none"
                >
                  <Box className="flex flex-col gap-1.5">
                    <Skeleton height={12} radius="sm" width={80 + i * 10} />
                    <Skeleton height={9} radius="sm" width={40} />
                  </Box>

                  <Box className="flex items-center gap-2">
                    <Box className="flex flex-col items-end gap-1">
                      <Skeleton height={14} radius="sm" width={44} />
                      <Skeleton height={8} radius="sm" width={52} />
                    </Box>
                    <Skeleton radius={'sm'} height={24} width={24} />
                  </Box>
                </Box>
              ))}
            </Box>

            <Box className="flex flex-col gap-2 px-1 pt-1">
              <Skeleton height={11} radius="sm" width="75%" />
              <Box className="flex items-center justify-between">
                <Skeleton height={11} radius="sm" width="45%" />
                <Skeleton height={34} radius="xl" width={90} />
              </Box>
            </Box>
          </Box>
        </Box>
      </Box>
    </Box>
  );
}
