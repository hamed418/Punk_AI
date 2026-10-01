import { Box } from '@mantine/core'

function PunkFind() {
  const data = [
    {
      title: 'Search behavior',
      description: 'What they look up online.',
    },
    {
      title: 'Location patterns',
      description: 'Places they visit in real life.',
    },
    {
      title: 'Purchase intent',
      description: 'What they’re eager to buy or switch.',
    },
    {
      title: 'Real-world visitation',
      description: 'Where they regularly shop and browse.',
    },
    {
      title: 'Household and lifestyle data',
      description: 'Demographic and daily signals.',
    },
  ]

  return (
    <Box className="w-full">
      <h2
        className="text-foreground my-3 text-xl font-bold"
        style={{ fontFamily: 'OCRX' }}
      >
        Punk finds your audience using:
      </h2>

      <Box className="space-y-1">
        {data.map((item) => (
          <Box
            key={item.title}
            className="bg-primary-widget/70 border-stroke-widget hover:bg-primary-widget flex flex-wrap items-center gap-1 rounded-xl border px-4 py-3 text-xs leading-4 font-semibold shadow-[0px_1px_2px_0px_#00000047] transition-colors duration-200"
          >
            <span className="text-secondary-text font-semibold">
              {item.title}
            </span>

            <span className="text-secondary-text font-normal">
              — {item.description}
            </span>
          </Box>
        ))}
      </Box>
    </Box>
  )
}

export default PunkFind
