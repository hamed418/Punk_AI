import { Box, Flex, Skeleton } from '@mantine/core';

export const AiSkeleton = () => {
  return (
    <Box className="flex flex-col gap-3">
      <Flex gap={4}>
        <Skeleton circle w={10} h={10} />
        <Skeleton circle w={10} h={10} />
        <Skeleton circle w={10} h={10} />
        <Skeleton h={10} w={80} />
      </Flex>
      <Box className="space-y-2">
        <Skeleton h={10} w={'60%'} />
        <Skeleton h={10} w={'80%'} />
      </Box>
      {[1, 2, 3].map((i) => {
        return (
          <Box key={i} className="flex w-full flex-col gap-1">
            <Flex className="w-full items-center justify-start gap-1">
              <Skeleton circle h={10} w={10} />
              <Skeleton h={10} w={i === 1 ? '40%' : i === 2 ? '70%' : '60%'} />
            </Flex>
            {i === 2 && <Skeleton h={10} w={'30%'} className="ml-3.5" />}
          </Box>
        );
      })}
    </Box>
  );
};
