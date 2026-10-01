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
  ];

  return (
    <div className="w-full">
      <h2
        className="text-xl font-bold text-foreground my-3"
        style={{ fontFamily: 'OCRX' }}
      >
        Punk finds your audience using:
      </h2>

      <div className="space-y-1">
        {data.map((item, index) => (
          <div
            key={index}
            className="bg-card/60 border hover:bg-card  shadow-[0px_1px_2px_0px_#00000047] rounded-xl px-4 py-3 flex flex-wrap items-center gap-1 text-xs font-semibold leading-4"
          >
            <span className="font-semibold text-foreground">{item.title}</span>

            <span className="text-foreground font-normal">
              — {item.description}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default PunkFind;
