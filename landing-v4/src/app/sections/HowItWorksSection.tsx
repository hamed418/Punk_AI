/* eslint-disable prefer-const */
'use client';

import { useEffect, useRef } from 'react';

declare global {
  interface Window {
    hiwSeek?: (n: number, t: number) => void;
  }
}

const HIW_MK0 =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAALAAAAC4CAYAAABD5GYzAAAhL0lEQVR42u2deZgVxbn/v9Xr2c/sGwyLyuaSzAwwMiOIKMriEpcENSYuiUm8MXpzTX7mmue5ilGzXpMb13hNrjEJgiSoqCCQYQmKIDIgooiIrMLs61l7q/r9MSyznK3HOeMMp77PM88Dfbq6q7s+/fZbb71VTcCVkfrL+wd+0cHIfz6+8xAAgFoW3XfrLBmE0OF0HQJvyszUN88b86upBf5TIIiiUPr0Gw8Nt+vgAGeoCCHtEoEhC+TkNkmWv8UB5ho2+qCx43B5vu8UwKpSmP/7NeM4wFzDQruOtb5yflHWKasMEJdi/g8HmGtY6Lmte56b4Hf12Car6mwOMNewUOt/3bhbM0zmU6RTQEiSMuKJld/lAHMNh54c23Gsta6y0N9jsyLJ93CAuYaFNu47trqyMKvHNskpj/c/9Wb2cKi/xJsws5S3cHGJINDZEMgYwjBm17GWaSUupZdhJsSP4K87gO9wgLmGlEQZk8CE50+EHQCgoTMMnyKhUzdPgaFICzAMAOYuRIapwet/izHWY7h43b5j6O0HS4riG/Hk67M4wFxDS3fP10DwfvdNb316DN2HlU9IFqVHOMBcQ0+MbOr+307NgALW1790qJVgjHCAuYaUCMPbvbfVH/eDe8AhCOKop1bezztxXOnVQiaMzH59riiReUSUpxIBBQGNTG++67JjsXbXBLpJ7WW7Nu0/hsqSAtQcaentC38HwIND9mHkrT+8NeKJFf/n8rhuI0JPIA1NbzlAs4vxvSlGrHIFDy2uIwRFJ/6viAJ+PGcqnvzgSE9vgzG0t0THNd0zdx93IbgGXJFweAmlff1XWVVyx6BlbwI/oocfrFsU1LL67kYInE7239wH5kqLWsMf1kTbO8KxflOcjjFjnn7j7ThN32d7WzDSxw/uehjUORxgrjT5vwupEY4uM6LRmD8rblfV6CdWLOq93YL1Vu9ta/d+1iceDACiJDpGPbny5kTV8D/28pm5v31tBAeYqx9iy6OtHaCMxYbY6/76qMdW9uiItYyXaxmD2X3bvqYOFDnk2L19SfpJohp4NPp1lyLcyQHmsq1Gl7SSGpaud4Ziu7uEQPE57x/x+xXfPLlxwQILhG3pvS81zJjHEB3KpMK/rHbHrYQozhMl6QoOMJd93bMgAoJ/ap0BWKYVu6EFAQ6v8/miR7sPD/f1g+s7gjH9YEIIcYSs38Q8+DPPyACZKsniBA4wVz+9CCwHY9DaO+MbSUkkTq+8Ku+RvxYDAEHfAY21e45gSoEvdnlZuSHW9rxm32WCJEiCLCvFv3t9EgeYy7YilriMASxPBG6fUJwIdEWg4vrsXy71R0zhzd4/d2oGPHFGByRFzi598o2pfSCi7EpBFLv8bVW8hwOcwcp74qXxo59aseyMP/4zdMYzaw5lP/NPfyrlOhcuaAWwuS4QwezSXMwoiZ+PTgiZoJjmmk6EwgzoM0ARjmpxy0oieTTGEa8UpC6UBFG4hAOcgSp9cuWPxv7vmsZsb87HqsdzraQoLsmpjsqRhLrCx16dlmo0AgB+umobHpk2Hn4lUaYAqSyQHEvAWB83oq4tgBK3Gqczp1Z3T/DJ/9nickJQQsSuc4mqMooDnIGyNO0MUZHzCSG9/E7J6fV63h7x1MofJudXWAYAO461YsOndXig8qyEuxPgKyDoM0ix7VAjynI98TqD4qinV9978hgCu7LL8oonfy95/I2rOMAZJkMzfhdubgOLEcsVRJG4PK7fjXn6jeWJjtH4Xzd8CrA9APCztTswc0QOZpfmJoGYFPbeplsUlm7GdyNk8fvdfOqrukA+9eDJAm7lAGeYmu5bsM+Kau9EOwLxQIPidl11xjNrDuU8ttIX1wgzshwAWsIafr/pQ9xfeVYSVyK2EvnBoqqU5jy5utT785dyCSGTiSii+5tDkMQLOMAZKMawVO8MQg9H4ls/pzoq2600FD29qjIm6Awvn/j3M+98jM6IjgfOt79a1MHGduTFGZUjAPGJ9FEn1a8DAHLcfThZR4eSj6VLFQ5wpgEsiYsBINLSjhEOEaoYu3lEWXZ4nOqWkv9++erevzXcf+M7AGs54Qrcv2Y7Lh+Tj/lj8m3V5YP6VnjF+HiIinoFYV3+ryiJvaMcZES959sc4Ax0IxjY+2AMpQR49uJz4ZSEeJ0pwqj5csHDS/rEXRnIshP/Xr+/Duv31+OBynEocNozii0dwfgAS6JTcMhXdFngvnWUVeFrHOAMFGFYCgCrPz6Cpe/tx98uK4NbFhN0wtijBQ8tXoaFzzlOuSK0R2fv/jXb4ZQEPFw13lZdWuPkVpyQ6nahewSi5wMmTeEAZ6CoJL144t+LaveiZt8xvDCnDN5EEBNcWyiq27IfWDoKAJoKgv8Ew8kc4U9aOvH0lj2YUZKD87Ocff1qgWDT96+AP9cP1e89+WdKiTt/sqsLYBIDYEmVvZ7HVuZzgDPRjWDYeeL/v6zZjt2N7VgyrxxZiaIJhJwjS+bOvEdenIXvfc9gwMruPz+2aTfO/d1LWP/J0T5FTcrwryPNuKH8LDj83lN/Pk/it4VAILudEKTYD1e2iLvS/sbiyAycSp5YcaksCDcTgYwHEUYIgpgjSMRpmWarqdH7j/xg7pOpHCf/oRfuEwj5+alGIlhy8yUYneXGjaveQ2u0a5pboL4RNEa8loH9BBCOErC/pVr3L5UW4OmvTMP8V7fZumYjqkOQxD4dOQDQw5EdB++YW8Et8HB5/evWMcmh3qi4nJWKUx0hqZJTEEXIqprj9DmfOOPZmvZRT668N6lVkdiLvYDEzS+sR0fUwN/nlaM4zjBvN+B/BdBb7NT9/SON0C2aMIciphvhUGLCezxakvbMNA7wAKr+nqs+1ILRW+LNjJBU2e/wun91xrM1gVFPrngg3nEa77tpP2PY0X2bZlpYsGg9dEqxdF45RnocySC+1G79l+4+jFsmjRyw+yHKkiPd6ZUc4AHWZ3fPX2R0hp5K5JtJquxxeD0Lz/xTTXjUkyt/hYWsTzswwpb23tYRiuCrL/wLAiFYOq8cY7M9A1r3v7+3HxcUZ+OMXqu2fx7JinQ3B3iY6dBdl9/pBduVrcpJLJTsdHjd955Zui5c+sSKR7tneVkgi2KVOdbSgRuXbYIqCnjkkvIBrXdzRxDbGtpxy8SBm5spSPbfBLwTNxT0taXiD+6Y0L6pMeAJGVbS3RljCBxr2MsM+mAD/XgJFi6kBQ8vriVAzE5Q6YgCHG1qjdmJOwmPIkFyOiA7naCmhXBza9IGv2na2Xh45rmYuWwLOhIcO+V+gWXRfbddLHILPNz09wXW28dC5XeePdIUUzAThBAoHvd4CFhUII7fk//I4lsZY/+It//ho42gJu0VfQBEVYUj2w9PSSG8RQVw+n2QFBmKywF3QS5AEldm+a79oGC4fnzxwAAmisLIx1+dxwEehtr+zep9++parrzzrAJE2jpgGYktmuJxg3XBPE5geI4A/5nw1Um7ABYdDjjzcuAvLYKnMBeq1x0zMiA7VLgL8gAhfrMHQ1GsPtiEmyaUQByg97MopO8DihzgNOuXcyevCunmgz8oG4NgXSOCjS3QQ+GYazgIogDF5exulX3Jjv/V88bg7spxkBwKCEnenJIqw1OYCyRI1Hlx10EUuVTMGT0wA2mCIk3nAA9j/WTmeQtLfe6Nt08dDyuqIdLSjsDRhphWWfG6bR172a6DuHB0AeYVeMBStYiyDE9hPsgJK93Lrdj4yWd4fOchWJQNyPVLilzIO3HDXYyRTYcaG559d2/+Gx9/1hMohwrF7YTkckIgBIGGJlDNSPnQeS4VK267FA9u3I1NHdHUO1iUghAg0toBI9QzB9lTnA9RlmNcBgU1KESbSfLhjvDtn90170/cAg9XEcK2HGqc/P9mnKtXjOg5zae3VZYdDluHbg5ruH3ZJjx6aRkmqKl3+AVBACECRLlvmqXWGYIeDCPS0YlQcxsC9U3oOFqPziP1CNY3wjTsRShECTdyF2KY60czzzvy5uGGrzx77QVsTKxBCEqhB0LQ4kwrAroSaERVhuxxwZHlhyMnCwzArvo2LKzZgT9fORVFgr1XvxDDmhqhMCKt7dA7gjDDEVDdAKxTUQ+qGzYBltOSXsldCJsq/O2K8xxOcj+jaKaUbjKZsLr+7vlNdo7x0gcHHy0ryb3n8ufWoDWipwaZqsCdlx0z91YLBBFt61qR59fzpuDCsUW4YUUt2lL4vIVlGNA6g31ciGSSvW64sv0p788YgxYK5hz+/hVtHOBBVu5vXxvhckiPyLJ4laiq2b1vmmWaFizablnWoc629qdlCx8Yprm7deE34q7ztPaTo1v8TvX86/62DlHTSqkeroJcyI7YiTyhphaYEQ2SQLDytsugiAIWrNwBLUbIjDEKPRSFEQzBsmlJT1pUVYGnMM9WmUggdP+RO+c/1Atssba29nsAblYUpSwajX67srJyEQd4gOT5zUsFuS7nfsXjdJ+YeTt3dB5WHWqO3VlpboUR7upIMbA6MHxICNnNGNlDwT4SLXV3w8JrGxlj8gcN7ccOtwfzvvvSJpgp9PiJJMFTnA8hxmAEtSiCDU1gpoURPhdWf2sO9jR34NvrPgSORxss3YAWDEEPRUAY+9ymz19aYquIHorWHvy3OVO2bt1aKknSjwkhV8qyPIZ0m9IcjUbfmDx58nwO8ACq4BeLziBE3qS6XUWK1407vjQa+zvCfT6IAgCGpiHc0JL4dQrWBkY+GJ3tal5x62XXrPu0Dv/+2jsp1UU9nmweS6amI9TQAoBh2qh8/P2mWVj+0RHcu3E3oqGwrchGKnLmZoPEmLMnygoEIQZahkGXTs7rlCQpi8QZETQMo7WsrCyXAzzAyn5g6ShFNjeCCKPz87Lwt2uqsGDVezHgBILHGkFNMz0VIQSe4oK4ObhaMIxoazsA4DuV43FLxTjc/doWbD/aMmj3ypmbDcXtjPnbE5P8GOFKnOR0zjnnpMwlj0KkqLYHFxy2TFLNGN3f1NSGdw7UY3auC5Zh9LEIisedvoowhmhbR8xOkmWYIAI5OUft2a17Mf0PKwYVXgAwIvE7hK8eDSQtX1tbey8HOA1qXnjjMWI6qhhjHz+15SP8aNoEhOubEWxshdltJRvZ7QRLYz3MSBTRziCigRDCLe0I1Deh87N6BOsaEWluA7OsL/Q+mREt5hJZALCjI7kbQwi5jgOcJjUsvLYxLEoz6jrDu96vb8M3ys+EFY0i1NiCQF0TtFAERCQ9chriGFIIkgjJ5YDq98KZlw1PSQEcOamFprT2TmhtHTBC4a6Y7OfolJ2T48KtEwsxf3TOgL0lzGjs8GATTSHCIYrncR84zfL/YlH27JHFm5++pmrClMdfhdYtyE8kEZKqwgjF/PoVFL8Hqs8bM5oAAMH6pn6Ht1JRqUdFeb4HlYUelOd7Ty6e0q6ZuHH1nh7XErMjKQpwiAQdenxLr3hccOZkxfztgTMdKMtKPJtE07QxFRUVh7gFTpM67rupbf2nxyobg5HQd8/v+WkIZlpx4QUAIxhOGMZSbQwQpCKXJOCCYh/u+lIJFs+ZhOcvnYAflo1AdbG/x8o/WaqEuaNiT+ocn+XA7efkYtHcEhy6bRT+ozwniR8cOyfDQU3oNHkHl1L6H9wCD4I+aw8v2N/W8YfrX/hXNrXxGlc8bjjjuAsMDFJHJ2vtCPW7fc7OcWFygQdT8r04Ly/1TmV9WMfXV+9BtiqiqtiNuaOduGSkilxnT1vXHqWY+LfDCY/lKcqHJIkokS3MLhBw65kKSlwiArqMIwFnMgu8t6KiYgIHeBBU+Ju/uBGVVoCQmSm7iSDwFOZCUrsSaRil8IFiil/GV0t98IgEt9XsRZuWWjguzymjusiHyQUeTC7wwiXZe7k6JAtuyYRbttAUiWKsP3m22U2rm7H2SM/105wiQXWxAxeNdGJinhMzivqGzCgj2NPqTXhsiRjRCWeXOTnAg6WFS5UCyXzdznT2bLcDBbl+TM9VcW2pH85eUyDWHmnDI9uOxCzrlASU5XkwpcCDqYVejPSotqqriF3AehQKl2RCFOx3Al8/EMLta5swKUfGrBFOXFzqRGWhA0oKUzkOdLgRMcVuD1BXPZyiAbdiGZIAGRLOJnlVH3GAbSrv4cVTBIb7QJgbDBFCEAEjYRBEGGMREEQYEBGYEAFYmDEWgYAIgWCCsd+BYGy8Y5/hc6Cq2IfqYh8mZSefvn7f2wfwTkNX7HRithOTC7yYXOBBWZ7HJrAUbtmCWzbh7iewsdQcsZDntD9nsy0qw6AC3LIFp2RCiE3iv5Oiqsc4wKm6Aj9beh4j1sOEYEC/8VCW50Z1sQ8XlPhR7LK3xGl9WMeetggm53vgVVIHRSQUHuU4sLIFWaDDr0EYVpHiqoQTQiWObbf7JRshZgnvE6AcQGl/j+OWRVQWelFd5MW0Il/C5VGTqciloCgF6AXCjsNqwi1ZUCV6OrTILMY+UQkZp3ELbFP5D70wl4B8mxB8NdUyXxmbi+klfkwu8KS9fgQMbuVEx8uE47QANqYuJUVVNRzgfipr4ctZshj5JiH4FgEpSwBUy9prvpybzrooIkWWasAtm3BKVmY0ACO/IcXT7uUAD4RV/tnicoGw2wByEwh6RfJZw7prvlyYzvO7ZROjfeFMu+3vk6KqL3OAB1ILlyr5gnk1EfAtMFxKCBEEgiM1V3+pNN2nnpgTgEBYht1wWkiKLmjkAKdBD7687pJ9HdFfHAvp5z520Thnus83whOBXzUy6yYTdgsprP4Lj0IMgLZt21ZMCLmTEHKFKIqTJElSBvP8AUPOPIAZmQOAA9wf7dy5022a5ncYY9dJklQmSZKHkC/uxRXQRTCWdI2+Ya3Wtk6sffNd1Ly5DTUb38Vrf/31FfH25QD3ftgZI9u2bbteEIRvEEKmCYKQ67C50Ei6FbXE0yoKEY1qeGvr+6jZ+C5q3nwXO3btBaWnwoJrNmz1sabNFSS/ajsHOIk2b958pt/vf2Eo9Q9UkcKjmPDIJlySOeytL6UUO3btRc2b76Jm47t4a+tORKPx18fY8PYO/PC7188BsJ134lLQe++91ynLsveLOr9AGDyyeRxaC5Jw+gxStLZ1Ylz119Da1plymewsL1o+Wr1BKK6e1edecVz7yjCMtwb7nE7JRL5Tw1h/CBNzAhjpjSBLNU4reAEgJ9uH/Fx7X0Jqaw9gS+0HM1j9TjcHOAWZpvn4YJwn22FgpCeMiTmdGOsPI9+lZcQI29xZ02yXWb3hHREsehEHOAVVVVW9YRhG2mNV2aoOnxo3lZAD3MMP3g4QOpcDnKIsy9qZ7nME9MzsQ8+6oAKqai98vqX2Q7S0dszjAKcoTdOeT/c5gkZmAqyqCqZNPsdme+h48533zmQtW0s5wClIUZRnaPdgZBoUMUVYNDMDQf1zI3YApjmfA5yCpkyZYmiadjDtbkSGWuF++8GUXNZ9Gx/ISByNeAnAj9PtB2elKbehMxDCa2vewiurNoIxhn/88edD5t5++ZxxKB1RiCNHGxLuN+Gs0ZhZVY6ZVeW4cFoZQDCHMUYI6UrJ4wAn8lGDwV+63e4fC0L6XlTBAe7IHa1rwvJVG/HKqo3Y8PZ2GMe/ZaEoMgLBELzpXHjQhgghuHj6ZDz/4soe284eP7YL2OpyzKquQH5en5ixG41bqgFs4gAn0ezZs1tqa2tbHA5H2mZaMBCEDBFuuf/x3/d378Mrb2zEK6v+hR279sbcR9cNLFuxAbdef/nQiUZUT8Z7H3xy0sJeVF2BnGxf8oJdbsQmgA8lJ9WWLVsWe73eG9J5jhyHhiK3ZqvMwSN1ePxPf8fyVRvx6cGjKZW5as4MLH/+16dDs7xDiqqm8U5cCjIM438YS+8MiIAu2y5T39iC3/5hccrwAsCq9VsQCIZOh2apZG07sjjAKWjGjBnvaJqmp/UhoQJ0y15TnF9xDooK7Hk2um5gRc3bp0OzEEQjl3KAU5RlWbZb3S2bUMXU/Vq7o3KEEHxl7gzb1/LKGxtPj0YhXeE0DnAKikQif0jmRsgiRbZDR6m3KzlntC+MHEfqhjto2Hcjbrj6UttlVq59G7p+GkxJYpjDAU5Rsiy/ahgG630H3bKJQlcUZ/qDGJcVRLE7Cq9yKjnHo5hAih8bCBkiGLPXp55ZVW7bjQgEw1i59jRwIwhKWfPmSRzgFFRdXR0xDGO3JFBkqTpKvRFMzAlitC+MXKcedxknWWBw2lgxJ6DbW4Kqv27EkldqTo+GMcllPA6c6C3Ftslo0qpAhfm6ZeUqYtD2MbyK0WMZ0WRuhE+193mu6y6fhWf+8oqtMlt37AZjDGS4z01ibA4HuPc9adhSCEavACPz0WDMBgQfACj9XJ/Pp5hoTHExnf7kRcysKofX40IgmPgkE84ajavnXoir512IyvKzhz+8QAOAAxkPMGNMROPm88HIPDDMB2PlACEDNcSjiBSKaEG3kj8BFiWImPZmHCuKjPmXVOPF5TV93IupZZNw9bwL8bUrL8FZY0cO95ZqB7ABDDWQsZbkVe8BMngomdVvvh7ANajffBkIyT7eMUiLfIqJ5khqJjyg258yf8PVs/Hi8hrIsoSLqitw9dwLcd0Vs1CYnzOcLUsUBJsArAVjNSiqriWE0L59ucwFeAmA6wfjXBFTxIGO1JJoHBLFGX57vnY0quEfr6/HVXNmwOd1nwaNw1aT4uq5qeyauVEIwpYM1qkcogWJpBaNiJqC7SR3h0PFN7469/SAt0sVqe6YuQAXaK8DLDgozwoBvDaiC516hndNCMlnjVvLOMAJ79EsE4wsG6zzeeXUR7/6Myp32olS7kKkoD8P1oncspXyur7B4wv4ZbbYHA5wMitcXLUBXfHEQXEjPHJqbsSJJPcMB3h6rJV4OMB9b9SgdebsjLJxN4JIQGQ2Bzj5S2jQAHZLBlJN7sn4jhwAMDaXA5zsOS+atgVgnw7GuUQB8ChWnLbqCbZJBWhmJjcPq4PA6pLtxR/zLoz/AeAngxWNiDUTOVZuQtCUoUrx58oZVECnLqMjKqLApR9P3xyuvCIMYAMIWQOJrj4xVMwBTsmLEJeAWoMCsEcxgRBDKoOgAV1Ebq/F4XVLQKcuoVOXEe2W5RY06HADmAF4HwSrwdgaFPneJORc21O3+Kzkky+st/eAkAmDca7eX2pPpIk5AZiUdFlaTYIWJylIEijGZweH+l1uBMg/QchqUGUVKa5o+rxH5Bb41LO8BMADg+JG2MgR3tfuhkmT+8ImFaBZAlRxaC2IHdHYAaeKZyEKa0h+Ve1AH58DfEIyWwKTDArAdnKEU4H3lMshQXXqX+htDGsUrSGK1qCFthAFZfjjxRdf/It0nY8DfML+5lXvYfWbdwL4crrPZSdH2I6Choy8QQbYtBjaQhStIQstQQrNYLF8XXCAB4Vi8lcwllaAI6aIoC6BsoHvfoQNEZSRtH+KtjNC0RrsgrYjnNRlIRzgQetjWH8FhN8M5E23KEHQkE7+pXs94IAuDfiXPDWDoTVE0RIw0RqisIaQm80B7m4qii5oZHWbN4Jg5kBY2aAhpdxZG0oAUwq0hylagl3AhrWhm1nEAe6mLVu2jKwLQir22muwwbayif3g/jVpMNrV8WoNUbSH6bDJhst4gLdv3z7asqz7JUm6Upbl/E6DoYgFk34N84u0sgmtJyMIGxJcSTLfDLPLLWgNWWgJWDCG6de9pB07drSnxZ1k7EBFRUX5UL3wbdu2TRRF8S1FUXosbWOxrlTG3jkLQ8nKJnUjDLEPwIwBHeEuYFtDFIEITaUNB2L6fXqjEIqi+NNxYMMwxg7lJ9cwjHFOpzPmukydugKPEhmyVjYVP7jQpSGis5MWti1EYVF7QPYH3hjQ8yjEYKtDkxAwvMPyC0K6riOgaWhu1hDR6WnfVhzgmO88MqRCRcksnqZpJ/9Yhs1F4gAPQ1mWdRJYXdcz+l5wgIeRa3ACWsuy+A3hAA9tUUqh6zp0XUc0Gs0414ADPMzhbWpq4jciBfFJnUO0Y8bFAebiAHNxnSY+sNWllCddMcYODOULl2V5yEZ6GWNQFCXhPqZpglJ7l+B3iRBtmKyoQRH5/FG6oZHQbprmjoqKiqmny5NrWdaQHWYjhCA7OzvhPsFgEKGQva9ujsmTkOtNfUj8cIuBTxs+90zn76xbt26OjYf3Z5dccsm6dEQhTqsZzJRSPiN7cDT2+F+qKuQ+MBfvxHFxcYC5uDjAXFwcYC4OMBcXB5iLiwPMxcUBHubqT8YatVmmP0lxg/0RcZ4PPEylKAq8Xq+tMqoSBEBtwNi/B2swIbYD8JBOUq2trd1gs0gufwyGoEsgCCxdAA/Z3IFt27b5HQ7HzKFUJ49iYpQ33K+yYVPEwQ53RgJsN0eF+8BcvBPHxcUB5uLiAHNxgLm4hpF4HJgrror8ErJdyacgfVynIxBlHGCuoSVFIlCk5FEtSRQAfDHLXXEXgou7EFwDK4KuafOJxBhLuk9vHQ1IaAwntqhexUKhp/8zkYdsLoQkSWXp+hzB527wNN80n2pCFey9IpXP8clXygBJStw0lmUl3adPGSqAscQvXRMGgC/uo+FpG0oWu+RHBsqnGPApxiA+kJn79uFDyVwZJQ4wFweYi4sDzMXFAebKNPE4MFcPRUwBDWEHgK5YdCQSSVom/AV+j44DzNVDuiWiJdKV/6DrQFubOaTry10IruHtQui63jHcL0IURY8oimn7mHFrGO2MSjtT3f9wc3Q6Y0i5PqKAHl8GtZgFI8mcdkLIgI5AGobRZ6r+F/E9OtsjceXl5VnDHeDt27dvEkWxOl3Hb2g3D4+dNu2iVPevqamxBOHzvtwSr+3vdDrhdg/cxM9AIGA7tyId4iNxaRBLlkDAxX3gIX2TBIF/joADPKzFAR6qnTh+CzjAx33qr02dOvUf/Sm7fv36Wxhjf+YWeKjSSwi3wNyF4ABzcYC/EPEoBAeYW2AuDjDvxHH1Fo9CpHKTJMn50UcfdV++NThp0qTaBBbbAKCmenzLsmAYp+bciaKoybIcTuLWOAzDcNp0heIOP0ej0SufffbZS2PUbdEdd9yxMdFxKaU0lZdUKqvKE0LOramp6VEPh8Px4fTp049xgPspRVFKKKUbum16D0B5goaS7XgdoiiieyrHhx9+eOiuu+6akKjM9u3b98qyPM7OdVBKEW+IOycn5+bq6r6j8Zs3bx4FICHAgiAIKcKZSjV/KgjCT7tv0DTtNgB/5i4EF/eBubg4wFxcHGAuLg4wFweYi4sDzMXFAebiAHNxcYAzXZ839yeVmbmUUtsfpaC0XwuQ0CFwS+NOj/7/OCSGZ/PZfUMAAAAASUVORK5CYII=';

const HIW_MK1 =
  'data:image/png;base64,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';
const HIW_MK2 =
  'data:image/png;base64,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';

export function HowItWorksSection() {
  const containerRef = useRef<HTMLElement>(null);
  const h2Ref = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    const root = containerRef.current;
    if (!root) return;

    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const steps = Array.from(root.querySelectorAll<HTMLElement>('#hiw .hstep, #hiw > article'));
    if (!steps.length) return;
    const stages = steps.map((s) => s.querySelector<HTMLElement>('.hstage, [data-stage]')!);
    const canvases = stages.map((s) => s.querySelector<HTMLCanvasElement>('canvas')!);
    const tracks = steps.map((s) => s.querySelector<HTMLElement>('.hstep__track i, [data-track] i')!);
    const dotsEl = Array.from(root.querySelectorAll<HTMLElement>('#hiwDots i'));
    const PINK = '#F02D8A',
      PINK_SOFT = '#FBD3E6',
      PINK_DARK = '#C21D6F',
      INK = '#141414',
      INK2 = '#4E4B48',
      MUTED = '#7A7672',
      LINE = '#DAD6CF',
      CARD = '#F4F3F0';
    const MONO = '"JetBrains Mono", ui-monospace, monospace',
      BODY = '"Inter", system-ui, sans-serif',
      DISPLAY = '"Bricolage Grotesque", "Inter", system-ui, sans-serif';
    const seeded = (i: number) => {
      const x = Math.sin(i * 12.9898) * 43758.5453;
      return x - Math.floor(x);
    };
    const clamp01 = (p: number) => Math.min(1, Math.max(0, p));
    const ease = (p: number) => {
      p = clamp01(p);
      return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
    };
    const easeOut = (p: number) => {
      p = clamp01(p);
      return 1 - Math.pow(1 - p, 3);
    };
    const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
    const seg = (t: number, a: number, b: number) => clamp01((t - a) / (b - a));

    const PERSON = [
      '....###....',
      '...#####...',
      '..#######..',
      '..#######..',
      '..#######..',
      '...#####...',
      '....###....',
      '...........',
      '...#####...',
      '..#######..',
      '.#########.',
      '###########',
      '###########',
    ];
    const ARROW = [
      '#...........',
      '##..........',
      '#.#.........',
      '#..#........',
      '#...#.......',
      '#....#......',
      '#.....#.....',
      '#......#....',
      '#.......#...',
      '#........#..',
      '#.........#.',
      '#....######.',
      '#..#.#......',
      '#.#..#......',
      '##....#.....',
      '#.....#.....',
      '.......#....',
      '.......#....',
    ];
    const CHECK = [
      '.........#',
      '........##',
      '.......##.',
      '#.....##..',
      '##...##...',
      '.##.##....',
      '..###.....',
      '...#......',
    ];
    const UPARROW = [
      '...#...',
      '..###..',
      '.#.#.#.',
      '#..#..#',
      '...#...',
      '...#...',
      '...#...',
    ];

    function sprite(
      g: CanvasRenderingContext2D,
      pat: string[],
      x: number,
      y: number,
      sc: number,
      col: string
    ) {
      g.fillStyle = col;
      for (let r = 0; r < pat.length; r++) {
        for (let c = 0; c < pat[r].length; c++) {
          if (pat[r][c] === '#') g.fillRect(x + c * sc, y + r * sc, sc, sc);
        }
      }
    }

    function person(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      col: string,
      sc: number
    ) {
      sc *= 0.55;
      const w = 11 * sc,
        h = 13 * sc;
      sprite(g, PERSON, Math.round(x - w / 2), Math.round(y - h / 2), sc, col);
    }

    function pointer(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      sc: number,
      down: boolean
    ) {
      if (down) {
        x += 1;
        y += 1;
      }
      for (let r = 0; r < ARROW.length; r++) {
        for (let c = 0; c < 12; c++) {
          if (ARROW[r][c] === '#') {
            g.fillStyle = '#fff';
            g.fillRect(x + c * sc - sc, y + r * sc - sc, 3 * sc, 3 * sc);
          }
        }
      }
      sprite(g, ARROW, x, y, sc, INK);
    }

    function dotGrid(g: CanvasRenderingContext2D, W: number, H: number) {
      /* no grid: the videos sit on a clean sheet */
    }

    function slab(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      w: number,
      h: number,
      step: number,
      fill?: string
    ) {
      g.fillStyle = '#CFCBC2';
      g.fillRect(x + step, y + step, w, h);
      g.fillStyle = 'rgba(20,20,20,.14)';
      g.fillRect(x - 1, y - 1, w + 2, h + 2);
      g.fillStyle = fill || '#fff';
      g.fillRect(x, y, w, h);
    }

    function text(
      g: CanvasRenderingContext2D,
      s: string,
      x: number,
      y: number,
      font: string,
      col: string,
      align: CanvasTextAlign = 'left'
    ) {
      g.font = font;
      g.fillStyle = col;
      g.textAlign = align;
      g.textBaseline = 'alphabetic';
      g.fillText(s, x, y);
    }

    function readout(
      g: CanvasRenderingContext2D,
      s: string,
      x: number,
      y: number,
      dark: boolean,
      align?: CanvasTextAlign
    ) {
      g.font = `500 ${11 * SC}px ${MONO}`;
      const w = g.measureText(s).width + 16 * SC,
        h = 22 * SC;
      const x0 = align === 'right' ? x - w : x;
      g.fillStyle = dark ? INK : 'rgba(255,255,255,.9)';
      g.fillRect(x0, y, w, h);
      g.fillStyle = dark ? '#fff' : INK2;
      g.textAlign = 'left';
      g.textBaseline = 'middle';
      g.fillText(s, x0 + 8 * SC, y + h / 2 + 1);
      return { x: x0, y, w, h };
    }

    function wrap(g: CanvasRenderingContext2D, s: string, maxW: number) {
      const words = s.split(' '),
        lines: string[] = [];
      let cur = '';
      words.forEach((w) => {
        const test = cur ? cur + ' ' + w : w;
        if (g.measureText(test).width > maxW && cur) {
          lines.push(cur);
          cur = w;
        } else cur = test;
      });
      if (cur) lines.push(cur);
      return lines;
    }

    let SC = 1;

    const PLACES: [number, number, number, string][] = [
      [0.36, 0.4, 487, 'Runyon Canyon'],
      [0.6, 0.24, 478, 'Silver Lake'],
      [0.24, 0.62, 344, 'Venice'],
      [0.72, 0.48, 302, 'Griffith Park'],
      [0.5, 0.7, 256, 'Culver City'],
      [0.83, 0.74, 188, 'Long Beach'],
    ];
    const TOTAL = PLACES.reduce((n, p) => n + p[2], 0),
      TOTAL_S = TOTAL.toLocaleString('en-US');
    const PROMPTS = [
      {
        text: 'People in LA who go to dog parks, for my dog treat brand',
        find: 'Finding devices seen at dog parks across LA',
        count: `Found ${TOTAL_S} devices`,
      },
    ];
    const CYCLE = 7.8,
      RUNS = 1;
    let baseIx = 0;
    const MK = [HIW_MK0, HIW_MK1, HIW_MK2].map((src, i) => {
      const el = document.getElementById('hiwMk' + i) as HTMLImageElement | null;
      if (el && el.complete && el.naturalWidth) return el;
      const img = new Image();
      img.src = src;
      return img;
    });

    function monkey(
      g: CanvasRenderingContext2D,
      i: number,
      x: number,
      y: number,
      h: number
    ) {
      const m = MK[i % MK.length];
      if (m && m.complete && m.naturalWidth) {
        g.imageSmoothingEnabled = false;
        g.drawImage(m, x, y, h * (m.naturalWidth / m.naturalHeight), h);
      }
    }

    function scene1(g: CanvasRenderingContext2D, W: number, H: number, t: number) {
      dotGrid(g, W, H);
      const run = Math.max(0, Math.min(RUNS - 1, Math.floor(t / CYCLE))),
        lt = Math.max(0, t - run * CYCLE);
      const ix = (baseIx + run) % PROMPTS.length,
        P = PROMPTS[ix];
      const u = SC,
        cx = 24 * u,
        cw = W - 48 * u;
      g.font = `500 ${11.5 * u}px ${MONO}`;
      const L = wrap(g, P.text, cw - 86 * u).length,
        ch = 20 * u + L * 16 * u + 16 * u,
        cy = H - ch - 30 * u;
      if (run === 0) {
        g.globalAlpha = 1 - seg(lt, 0.2, 0.6);
        text(
          g,
          'Describe who you want to reach',
          W / 2,
          cy - 26 * u,
          `500 ${11 * u}px ${MONO}`,
          MUTED,
          'center'
        );
        g.globalAlpha = 1;
      }
      slab(g, cx, cy, cw, ch, 4 * u);
      monkey(g, ix, cx + 12 * u, cy + 11 * u, 19 * u);
      const bx = cx + cw - 36 * u,
        by = cy + 12 * u,
        bs = 24 * u;
      const clickT = 3.5,
        clicked = lt > clickT && lt < clickT + 0.22;
      g.fillStyle = clicked ? PINK_DARK : PINK;
      g.fillRect(bx, by, bs, bs);
      sprite(g, UPARROW, bx + 5 * u, by + 5 * u, 2 * u, '#fff');
      const typed = P.text.slice(0, Math.floor(seg(lt, 0.35, 3.1) * P.text.length));
      g.font = `500 ${11.5 * u}px ${MONO}`;
      const sent = lt > clickT,
        lift = ease(seg(lt, clickT, clickT + 0.5));
      if (!sent) {
        const lines = wrap(g, typed, cw - 86 * u);
        g.fillStyle = INK;
        g.textAlign = 'left';
        g.textBaseline = 'alphabetic';
        lines.forEach((l, i) =>
          g.fillText(l, cx + 40 * u, cy + 26 * u + i * 16 * u)
        );
        const last = lines[lines.length - 1] || '',
          lx = cx + 40 * u + g.measureText(last).width + 2 * u,
          ly = cy + 16 * u + Math.max(0, lines.length - 1) * 16 * u;
        if (
          Math.floor(lt * 2.4) % 2 === 0 ||
          (lt > 0.35 && lt < 3.1)
        ) {
          g.fillStyle = PINK;
          g.fillRect(lx, ly, 2 * u, 13 * u);
        }
      } else {
        g.font = `500 ${11.5 * u}px ${MONO}`;
        const mw = Math.min(cw * 0.74, 250 * u),
          lines = wrap(g, P.text, mw - 20 * u),
          mh = lines.length * 16 * u + 18 * u;
        const mx =
            cx + cw - Math.max(...lines.map((l) => g.measureText(l).width)) - 20 * u,
          my = lerp(cy, 40 * u, lift);
        g.fillStyle = '#fff';
        g.fillRect(mx, my, cx + cw - mx, mh);
        g.fillStyle = 'rgba(20,20,20,.14)';
        g.fillRect(mx, my + mh, cx + cw - mx, 1);
        g.fillStyle = PINK;
        g.fillRect(mx, my, 3 * u, mh);
        g.fillStyle = INK;
        g.textAlign = 'left';
        g.textBaseline = 'alphabetic';
        lines.forEach((l, i) =>
          g.fillText(l, mx + 12 * u, my + 20 * u + i * 16 * u)
        );
        const rt = ease(seg(lt, clickT + 0.5, clickT + 0.9)),
          FOUND = clickT + 2.4;
        if (rt > 0) {
          const ry = my + mh + 22 * u,
            mkH = 26 * u;
          g.globalAlpha = rt;
          monkey(g, ix, cx, ry - mkH + 11 * u + (1 - rt) * 5 * u, mkH);
          const looking = lt < FOUND;
          const said = looking
            ? P.find + '.'.repeat(1 + Math.floor((lt * 2.5) % 3))
            : P.count;
          const lines2 = wrap(g, said, cw - 52 * u);
          lines2.forEach((l, i) =>
            text(
              g,
              l,
              cx + 32 * u,
              ry + 2 * u + i * 14 * u,
              `500 ${10 * u}px ${MONO}`,
              looking ? MUTED : INK,
              'left'
            )
          );
          g.globalAlpha = 1;
        }
      }
      const pt = seg(lt, 3.15, clickT - 0.05);
      if (lt > 3.05 && lt < clickT + 0.45) {
        const px = lerp(W - 30 * u, bx + 10 * u, easeOut(pt)),
          py = lerp(H - 20 * u, by + 9 * u, easeOut(pt));
        pointer(g, px, py, 1.4 * u, clicked);
      }
    }
    const PARK_W = 0.12,
      PARK_H = 0.1,
      PARK_ZOOM = 4;
    const PHONE = [
      '.#####.',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '#######',
      '.#####.',
    ];
    const TREE = ['.##.', '####', '####', '.##.'];
    const TREES: [number, number][] = [
      [-0.43, -0.36],
      [-0.31, -0.41],
      [0.43, -0.37],
      [0.44, 0.36],
      [0.33, 0.42],
      [-0.44, 0.38],
    ];
    const devs: { nx: number; ny: number; at: number }[] = [];
    (() => {
      let k = 0;
      while (devs.length < 38 && k < 9000) {
        k++;
        const nx = (seeded(k * 1.7 + 3) - 0.5) * 0.86,
          ny = (seeded(k * 2.3 + 11) - 0.5) * 0.82;
        if (devs.some((d) => Math.abs(d.nx - nx) < 0.078 && Math.abs(d.ny - ny) < 0.153)) continue;
        if (TREES.some(([tx, ty]) => Math.abs(tx - nx) < 0.09 && Math.abs(ty - ny) < 0.15)) continue;
        devs.push({ nx, ny, at: seeded(k + 5) });
      }
    })();

    function mapLayer(
      g: CanvasRenderingContext2D,
      W: number,
      H: number,
      a: number,
      k: number = 1
    ) {
      g.globalAlpha = a;
      g.fillStyle = '#CFE3EE';
      g.beginPath();
      g.moveTo(0, 0);
      g.lineTo(W * 0.16, 0);
      g.bezierCurveTo(W * 0.1, H * 0.35, W * 0.2, H * 0.6, W * 0.08, H * 0.82);
      g.bezierCurveTo(W * 0.04, H * 0.9, W * 0.02, H, 0, H);
      g.closePath();
      g.fill();
      g.strokeStyle = '#fff';
      g.lineWidth = 5 * SC * k;
      g.beginPath();
      [
        [0.08, 0.18, 0.98, 0.14],
        [0.1, 0.5, 0.95, 0.42],
        [0.18, 0.84, 0.96, 0.8],
        [0.28, 0.02, 0.3, 0.98],
        [0.55, 0.02, 0.53, 0.98],
        [0.78, 0.02, 0.84, 0.98],
      ].forEach(([x0, y0, x1, y1]) => {
        g.moveTo(x0 * W, y0 * H);
        g.lineTo(x1 * W, y1 * H);
      });
      g.stroke();
      g.strokeStyle = '#EDEAE4';
      g.lineWidth = 2 * SC * k;
      g.beginPath();
      [
        [0.05, 0.3, 0.95, 0.27],
        [0.05, 0.66, 0.95, 0.62],
        [0.445, 0.05, 0.465, 0.95],
        [0.66, 0.05, 0.69, 0.95],
      ].forEach(([x0, y0, x1, y1]) => {
        g.moveTo(x0 * W, y0 * H);
        g.lineTo(x1 * W, y1 * H);
      });
      g.stroke();
      // green block for each dog park
      PLACES.forEach(([x, y], i) => {
        const pw = i ? 0.1 : PARK_W,
          ph = i ? 0.078 : PARK_H;
        g.fillStyle = '#DCE6CB';
        g.fillRect((x - pw / 2) * W, (y - ph / 2) * H, pw * W, ph * H);
      });
      g.globalAlpha = 1;
    }

    function parkDetail(
      g: CanvasRenderingContext2D,
      W: number,
      H: number,
      detail: number
    ) {
      if (detail <= 0) return;
      const [cx, cy] = PLACES[0],
        x0 = (cx - PARK_W / 2) * W,
        y0 = (cy - PARK_H / 2) * H,
        pw = PARK_W * W,
        ph = PARK_H * H,
        px = pw / 173;
      g.globalAlpha = detail;
      g.fillStyle = '#E3ECD3';
      g.fillRect(x0, y0, pw, ph);
      g.fillStyle = '#EFEBDD';
      g.fillRect(x0 + pw * 0.08, y0 + ph * 0.56, pw * 0.84, 5 * px);
      g.fillRect(x0 + pw * 0.6, y0, 5 * px, ph * 0.56 + 5 * px);
      TREES.forEach(([tx, ty]) =>
        sprite(g, TREE, x0 + (tx + 0.5) * pw - 6 * px, y0 + (ty + 0.5) * ph - 6 * px, 3 * px, '#B5CB9A')
      );
      g.strokeStyle = '#A9B894';
      g.lineWidth = 1.5 * px;
      g.strokeRect(x0 + 0.75 * px, y0 + 0.75 * px, pw - 1.5 * px, ph - 1.5 * px);
      g.fillStyle = '#E3ECD3';
      g.fillRect(x0 + pw * 0.6 - 1 * px, y0, 7 * px, 1.6 * px);
      g.globalAlpha = 1;
    }

    function phone(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      sc: number,
      lit: boolean
    ) {
      const w = 7 * sc,
        h = 13 * sc;
      x = Math.round(x - w / 2);
      y = Math.round(y - h / 2);
      sprite(g, PHONE, x, y, sc, PINK);
      g.fillStyle = lit ? PINK_SOFT : '#fff';
      g.fillRect(x + sc, y + sc, 5 * sc, 11 * sc);
      g.fillStyle = PINK;
      g.fillRect(x + 2 * sc, y + 2 * sc, 3 * sc, sc);
    }

    function scene2(g: CanvasRenderingContext2D, W: number, H: number, t: number) {
      const u = SC,
        ZOOM_A = 3.4,
        ZOOM_B = 4.9,
        target = PLACES[0];
      const z = ease(seg(t, ZOOM_A, ZOOM_B)),
        scale = lerp(1, PARK_ZOOM, z);
      // the dive: everything scales about the target park, and the park slides to the middle of the stage as it lands
      const tx = target[0] * W,
        ty = target[1] * H,
        ox = lerp(tx, W * 0.5, z),
        oy = lerp(ty, H * 0.47, z);
      dotGrid(g, W, H); // the grid stays put; only the map dives
      g.save();
      g.translate(ox, oy);
      g.scale(scale, scale);
      g.translate(-tx, -ty);
      mapLayer(g, W, H, 1, lerp(1, 0.55, z) / scale);
      // the geofence: centred on the park and just wide enough to hold all of it
      const ring = ease(seg(t, ZOOM_A + 0.6, ZOOM_B + 0.3)),
        R = (Math.hypot(PARK_W * W, PARK_H * H) / 2) * 1.12 * ring;
      if (ring > 0) {
        g.fillStyle = 'rgba(240,45,138,.08)';
        g.beginPath();
        g.arc(tx, ty, R, 0, Math.PI * 2);
        g.fill();
      }
      parkDetail(g, W, H, seg(z, 0.35, 0.9)); // the park sits on top of the tint, so the lawn stays green
      if (ring > 0) {
        g.strokeStyle = PINK;
        g.lineWidth = (1.25 / scale) * u;
        g.setLineDash([(3 / scale) * u, (3 / scale) * u]);
        g.beginPath();
        g.arc(tx, ty, R, 0, Math.PI * 2);
        g.stroke();
        g.setLineDash([]);
      }
      // the pins: a pixel person on each park with the devices seen there
      let counted = 0;
      PLACES.forEach(([px, py, n, name], i) => {
        const q = easeOut(seg(t, 0.5 + i * 0.32, 0.9 + i * 0.32));
        if (q <= 0) return;
        const isT = i === 0,
          fade = isT ? 1 - ease(seg(t, ZOOM_B + 0.2, ZOOM_B + 0.7)) : 1;
        counted += Math.round(n * q);
        const x = px * W,
          y = py * H,
          k = (1 / scale) * u;
        if (fade > 0) {
          g.globalAlpha = fade;
          // the person, then the count on a plate above it
          person(g, x, y - 4 * k * q, PINK, 2.4 * k * q);
          const label = String(n);
          g.font = `500 ${11 * k}px ${MONO}`;
          const w = g.measureText(label).width + 12 * k,
            h = 18 * k,
            ly = y - 34 * k - 4 * k * (1 - q);
          g.fillStyle = PINK;
          g.fillRect(x - w / 2, ly, w, h);
          g.fillStyle = '#fff';
          g.textAlign = 'center';
          g.textBaseline = 'middle';
          g.fillText(label, x, ly + h / 2 + 1);
          g.fillStyle = PINK;
          g.fillRect(x - 3 * k, ly + h, 6 * k, 3 * k);
        }
        // the park's name stays under the fence once the map has landed on it
        if (isT && z > 0.6) {
          g.globalAlpha = seg(z, 0.6, 1);
          text(
            g,
            name + ' · dog park',
            x,
            y + PARK_H * H / 2 + 15 * k,
            `500 ${9.5 * k}px ${MONO}`,
            INK2,
            'center'
          );
        }
        g.globalAlpha = 1;
      });
      g.restore();
      // the devices: the count breaks into phones, and every one of them settles inside the park.
      // drawn in stage space (not inside the zoom) so each phone lands on whole pixels
      const pw = PARK_W * W * scale,
        ph = PARK_H * H * scale;
      devs.forEach((d, i) => {
        const q = easeOut(seg(t, ZOOM_B + 0.1 + d.at * 1.4, ZOOM_B + 0.6 + d.at * 1.4));
        if (q <= 0) return;
        g.globalAlpha = Math.min(1, q * 2.5);
        phone(
          g,
          ox + d.nx * pw * q,
          oy + d.ny * ph * q - (1 - q) * 6 * u,
          Math.max(1, Math.round(1.5 * u * dpr)) / dpr,
          Math.sin(t * 2.6 + i * 1.9) > 0.86
        );
      });
      g.globalAlpha = 1;
      // the readouts stay put while the map moves
      const u2 = u;
      if (t < ZOOM_B + 0.4)
        readout(
          g,
          `${PLACES.filter((_p, i) => t > 0.5 + i * 0.32).length} places · ${counted.toLocaleString('en-US')} devices seen`,
          14 * u2,
          H - 36 * u2,
          true
        );
      else
        readout(
          g,
          `${Math.min(
            target[2],
            Math.round(seg(t, ZOOM_B + 0.3, ZOOM_B + 2.2) * target[2])
          ).toLocaleString('en-US')} of ${TOTAL_S} · ${target[3]}`,
          14 * u2,
          H - 36 * u2,
          true
        );
      if (t > ZOOM_B + 2.4) {
        g.globalAlpha = seg(t, ZOOM_B + 2.4, ZOOM_B + 2.8);
        readout(g, '● matched', W - 14 * u2, H - 36 * u2, false, 'right');
        g.globalAlpha = 1;
      }
    }

    function field(
      g: CanvasRenderingContext2D,
      label: string,
      value: string,
      x: number,
      y: number,
      w: number,
      lines?: number
    ) {
      const u = SC;
      text(g, label, x, y, `500 ${9 * u}px ${MONO}`, MUTED, 'left');
      const h = lines ? 8 * u + lines * 9 * u : 20 * u;
      g.fillStyle = CARD;
      g.fillRect(x, y + 6 * u, w, h);
      g.fillStyle = LINE;
      g.fillRect(x, y + 6 * u + h, w, 1);
      if (lines) {
        g.fillStyle = LINE;
        for (let i = 0; i < lines; i++)
          g.fillRect(
            x + 7 * u,
            y + 13 * u + i * 9 * u,
            w * (i === lines - 1 ? 0.5 : 0.84),
            2.5 * u
          );
      } else
        text(g, value, x + 7 * u, y + 19.5 * u, `500 ${9.5 * u}px ${BODY}`, INK, 'left');
      return y + 6 * u + h + 16 * u;
    }

    function creative(
      g: CanvasRenderingContext2D,
      x: number,
      y: number,
      s: number,
      a: number
    ) {
      g.globalAlpha = a;
      g.fillStyle = INK;
      g.fillRect(x, y, s, s);
      g.fillStyle = PINK;
      g.fillRect(x, y, s, s * 0.16);
      text(
        g,
        "BECK'S BISCUITS",
        x + s * 0.5,
        y + s * 0.11,
        `500 ${s * 0.075}px ${MONO}`,
        '#fff',
        'center'
      );
      const BISCUIT = [
        '..####..',
        '.######.',
        '##.##.##',
        '########',
        '##.##.##',
        '.######.',
        '..####..',
      ],
        c = s / 14;
      sprite(g, BISCUIT, x + s * 0.5 - 4 * c, y + s * 0.28, c, '#E0B06A');
      text(
        g,
        '$10 OFF',
        x + s * 0.5,
        y + s * 0.84,
        `600 ${s * 0.17}px ${DISPLAY}`,
        '#fff',
        'center'
      );
      text(
        g,
        'FIRST ORDER',
        x + s * 0.5,
        y + s * 0.94,
        `500 ${s * 0.07}px ${MONO}`,
        'rgba(255,255,255,.7)',
        'center'
      );
      g.globalAlpha = 1;
    }

    function scene3(g: CanvasRenderingContext2D, W: number, H: number, t: number) {
      dotGrid(g, W, H);
      const u = SC,
        sx = 22 * u,
        sy = 36 * u,
        sw = W - 44 * u,
        sh = H - 62 * u;
      slab(g, sx, sy, sw, sh, 5 * u);
      text(
        g,
        'Campaign creative',
        sx + 16 * u,
        sy + 24 * u,
        `600 ${13 * u}px ${DISPLAY}`,
        INK,
        'left'
      );
      text(
        g,
        'Ready to publish',
        sx + 16 * u,
        sy + 38 * u,
        `500 ${9 * u}px ${MONO}`,
        MUTED,
        'left'
      );
      const fx = sx + 16 * u,
        fw = sw * 0.42;
      let y = sy + 62 * u;
      y = field(g, 'Headline', 'Your dog deserves better.', fx, y, fw);
      y = field(g, 'Call to action', 'Shop now', fx, y, fw);
      field(g, 'Body copy', '', fx, y, fw, 3);

      const px = sx + sw * 0.52,
        pw = sw * 0.48 - 16 * u,
        py = sy + 58 * u;
      g.fillStyle = CARD;
      g.fillRect(px, py, pw, sh - 96 * u);
      g.fillStyle = LINE;
      g.fillRect(px, py, pw, 1);
      g.fillStyle = PINK;
      g.fillRect(px + 10 * u, py + 10 * u, 12 * u, 12 * u);
      text(
        g,
        "Beck's Biscuits",
        px + 28 * u,
        py + 17 * u,
        `600 ${9 * u}px ${BODY}`,
        INK,
        'left'
      );
      text(
        g,
        'Sponsored',
        px + 28 * u,
        py + 26 * u,
        `500 ${7.5 * u}px ${MONO}`,
        MUTED,
        'left'
      );
      const ix = px + 10 * u,
        iy = py + 34 * u,
        is = pw - 20 * u;
      const DROP_T = 2.55,
        dropped = t > DROP_T;
      const start = { x: 30 * u, y: H - 70 * u },
        dragQ = ease(seg(t, 1.35, DROP_T - 0.05)),
        near = dragQ > 0.8;
      if (!dropped) {
        g.fillStyle = near ? 'rgba(240,45,138,.06)' : '#fff';
        g.fillRect(ix, iy, is, is);
        g.strokeStyle = near ? PINK : LINE;
        g.lineWidth = 1;
        g.setLineDash([3 * u, 3 * u]);
        g.strokeRect(ix + 0.5, iy + 0.5, is - 1, is - 1);
        g.setLineDash([]);
        text(
          g,
          'Drop files or browse',
          ix + is / 2,
          iy + is / 2 + 3 * u,
          `500 ${8.5 * u}px ${MONO}`,
          near ? PINK : MUTED,
          'center'
        );
      } else {
        const q = easeOut(seg(t, DROP_T, DROP_T + 0.3));
        creative(g, ix, iy, is, 1);
        g.fillStyle = PINK;
        g.globalAlpha = 1 - q;
        g.fillRect(ix, iy, is, is);
        g.globalAlpha = 1;
      }
      g.fillStyle = INK;
      g.fillRect(ix, iy + is + 10 * u, is * 0.7, 2.5 * u);
      g.fillStyle = LINE;
      g.fillRect(ix, iy + is + 17 * u, is * 0.9, 2.5 * u);
      g.fillStyle = LINE;
      g.fillRect(ix, iy + is + 23 * u, is * 0.55, 2.5 * u);
      g.fillStyle = '#DEDAD3';
      g.fillRect(ix + is - 46 * u, iy + is + 34 * u, 46 * u, 16 * u);
      text(
        g,
        'Shop now',
        ix + is - 23 * u,
        iy + is + 45 * u,
        `500 ${7.5 * u}px ${MONO}`,
        INK2,
        'center'
      );

      const PUB_T = 4.5,
        pressed = t > PUB_T && t < PUB_T + 0.3,
        live = t > PUB_T + 1.0;
      const bx = sx + sw - 82 * u,
        by = sy + sh - 34 * u,
        bw = 66 * u,
        bh = 22 * u;
      text(g, 'Back', bx - 22 * u, by + 15 * u, `500 ${9 * u}px ${MONO}`, MUTED, 'right');
      g.fillStyle = pressed ? PINK_DARK : t > PUB_T ? PINK : INK;
      g.fillRect(bx, by, bw, bh);
      text(
        g,
        t > PUB_T && !live ? 'Publishing…' : 'Publish',
        bx + bw / 2,
        by + 15 * u,
        `500 ${9 * u}px ${MONO}`,
        '#fff',
        'center'
      );

      if (t > 0.8 && !dropped) {
        const fade = seg(t, 0.8, 1.1),
          tx = lerp(start.x, ix, dragQ),
          ty = lerp(start.y, iy, dragQ),
          ts = lerp(56 * u, is, dragQ);
        g.fillStyle = 'rgba(20,20,20,.12)';
        g.fillRect(tx + 4 * u, ty + 4 * u, ts, ts);
        creative(g, tx, ty, ts, fade);
        if (t > 1.2) pointer(g, tx + ts * 0.55, ty + ts * 0.5, 1.4 * u, true);
      }

      if (dropped && t < PUB_T + 0.8) {
        const q = easeOut(seg(t, 3.3, PUB_T - 0.1));
        pointer(
          g,
          lerp(ix + is * 0.55, bx + bw * 0.5, q),
          lerp(iy + is * 0.5, by + bh * 0.5, q),
          1.4 * u,
          pressed
        );
      }

      if (live) {
        const q = ease(seg(t, PUB_T + 1.0, PUB_T + 1.5));
        g.fillStyle = `rgba(20,20,20,${0.28 * q})`;
        g.fillRect(0, 0, W, H);
        const mw = 176 * u,
          mh = 112 * u,
          mx = (W - mw) / 2,
          my = (H - mh) / 2 + (1 - q) * 10 * u;
        g.globalAlpha = q;
        slab(g, mx, my, mw, mh, 5 * u);
        g.fillStyle = PINK;
        g.fillRect(mx + mw / 2 - 14 * u, my + 18 * u, 28 * u, 28 * u);
        const cells: [number, number][] = [];
        CHECK.forEach((row, r) =>
          [...row].forEach((c, k) => {
            if (c === '#') cells.push([k, r]);
          })
        );
        cells.sort((a, b) => a[0] - b[0]);
        const n = Math.round(seg(t, PUB_T + 1.4, PUB_T + 1.9) * cells.length);
        g.fillStyle = '#fff';
        cells
          .slice(0, n)
          .forEach(([c, r]) =>
            g.fillRect(mx + mw / 2 - 10 * u + c * 2 * u, my + 24 * u + r * 2 * u, 2 * u, 2 * u)
          );
        text(
          g,
          'Your campaign is live',
          mx + mw / 2,
          my + 70 * u,
          `600 ${13 * u}px ${DISPLAY}`,
          INK,
          'center'
        );
        text(
          g,
          `Meta · 1 ad set · ${TOTAL_S} people`,
          mx + mw / 2,
          my + 88 * u,
          `500 ${9 * u}px ${MONO}`,
          MUTED,
          'center'
        );
        g.globalAlpha = 1;
      }
    }

    const SCENES = [scene1, scene2, scene3],
      DUR = [7.8, 9.2, 8.2],
      REST = [3.0, 2.95, 0.5];
    const ctx = canvases.map((c) => c.getContext('2d')!);
    let W = [1, 1, 1],
      dpr = 1;

    function size() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      stages.forEach((s, i) => {
        const r = s.getBoundingClientRect();
        W[i] = Math.max(1, r.width);
        canvases[i].width = Math.round(W[i] * dpr);
        canvases[i].height = Math.round(W[i] * dpr);
      });
      paintSleeping();
    }

    function paint(i: number, t: number) {
      const g = ctx[i],
        w = W[i];
      if (!g) return;
      SC = w / 360;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
      g.clearRect(0, 0, w, w);
      g.fillStyle = CARD;
      g.fillRect(0, 0, w, w);
      SCENES[i](g, w, w, t);
    }

    function paintSleeping() {
      SCENES.forEach((s, i) => {
        if (i !== state) paint(i, REST[i]);
      });
    }

    let state = 0,
      stateStart = performance.now(),
      visible = true;

    function setState(n: number) {
      const was = state;
      state = n;
      stateStart = performance.now();
      steps.forEach((s, k) => s.classList.toggle('is-active', k === n));
      dotsEl.forEach((d, k) => d.classList.toggle('is-on', k === n));
      tracks.forEach((el) => {
        if (el) el.style.width = '0%';
      });
      if (was !== n) paint(was, REST[was]);
      paint(n, 0);
    }

    let animId = 0;
    let lastNow = performance.now();
    function frame(now: number) {
      animId = requestAnimationFrame(frame);
      const delta = now - lastNow;
      lastNow = now;
      if (!visible) {
        stateStart += delta;
        return;
      }
      const t = (now - stateStart) / 1000,
        p = Math.min(1, t / DUR[state]);
      paint(state, reduced ? DUR[state] - 0.01 : t);
      tracks.forEach((el, k) => {
        if (el) el.style.width = (k === state ? p * 100 : 0) + '%';
      });
      if (p >= 1) {
        if (state === 0) baseIx = (baseIx + RUNS) % PROMPTS.length;
        setState((state + 1) % SCENES.length);
      }
    }

    const ro = new ResizeObserver(size);
    if (stages[0]) ro.observe(stages[0]);
    size();

    const stacked = matchMedia('(max-width: 900px)');
    let userJumped = false;
    let stepIO: IntersectionObserver | null = null;
    const hiwSection = root.querySelector('#hiw') || root;
    const sectionIO = new IntersectionObserver(
      ([e]) => {
        const wasVisible = visible;
        visible = e.isIntersecting;
        if (visible && !wasVisible && !stacked.matches) setState(0);
      },
      { threshold: 0.08 }
    );
    if (hiwSection) sectionIO.observe(hiwSection);

    function wireStacked() {
      if (stepIO) {
        stepIO.disconnect();
        stepIO = null;
      }
      if (!stacked.matches) return;
      stepIO = new IntersectionObserver(
        (entries) => {
          entries.forEach((en) => {
            if (!en.isIntersecting) return;
            const k = steps.indexOf(en.target as HTMLElement);
            if (k === -1 || k === state) return;
            if (userJumped) {
              userJumped = false;
              return;
            }
            setState(k);
          });
        },
        { rootMargin: '-45% 0px -45% 0px', threshold: 0 }
      );
      steps.forEach((s) => stepIO?.observe(s));
    }
    wireStacked();
    stacked.addEventListener('change', wireStacked);

    const stepListeners: { el: HTMLElement; click: () => void; key: (e: KeyboardEvent) => void }[] = [];
    steps.forEach((s, k) => {
      const go = () => {
        userJumped = true;
        visible = true;
        setState(k);
      };
      const onKey = (e: KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          go();
        }
      };
      s.addEventListener('click', go);
      s.addEventListener('keydown', onKey);
      stepListeners.push({ el: s, click: go, key: onKey });
    });

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => {
        paintSleeping();
        paint(state, (performance.now() - stateStart) / 1000);
      });
    }
    animId = requestAnimationFrame(frame);

    if (typeof window !== 'undefined') {
      window.hiwSeek = (n: number, t: number) => {
        setState(n);
        stateStart = performance.now() - t * 1000;
      };
    }

    return () => {
      cancelAnimationFrame(animId);
      ro.disconnect();
      sectionIO.disconnect();
      if (stepIO) stepIO.disconnect();
      stacked.removeEventListener('change', wireStacked);
      stepListeners.forEach(({ el, click, key }) => {
        el.removeEventListener('click', click);
        el.removeEventListener('keydown', key);
      });
    };
  }, []);

  useEffect(() => {
    const h2 = h2Ref.current;
    const s = containerRef.current;
    if (!h2 || !s) return;
    const orig = parseFloat(getComputedStyle(h2).fontSize);
    function fit() {
      if (!h2 || !s) return;
      h2.style.fontSize = '';
      const w = h2.scrollWidth;
      const avail = h2.parentElement?.clientWidth || s.clientWidth;
      if (w > avail && avail > 0) {
        const factor = avail / w;
        h2.style.fontSize = Math.max(22, Math.floor(orig * factor)) + 'px';
      }
    }
    const ro = new ResizeObserver(fit);
    ro.observe(s);
    fit();
    return () => ro.disconnect();
  }, []);

  return (
    <section
      className="section reveal"
      id="how-it-works"
      ref={containerRef}
    >
      <div className="wrap mx-auto w-[min(var(--max,1180px),calc(100%-40px))] max-sm:w-[calc(100%-32px)]">
        <div className="section__head section__head--center grid gap-0 mb-[clamp(32px,4vw,52px)] text-center justify-items-center">
          <h2
            ref={h2Ref}
            className="h-fit font-display m-0 max-w-none text-[clamp(28px,3.2vw,42px)] leading-[1.12] tracking-[-0.02em] font-medium text-balance text-(--ink) [@media(min-width:800px)]:whitespace-nowrap [@media(min-width:800px)]:text-nowrap"
          >
            Hand pick the exact phones your ads go to.
          </h2>
        </div>

        <img
          id="hiwMk0"
          src={HIW_MK0}
          alt=""
          aria-hidden="true"
          className="hidden"
          style={{ display: 'none' }}
        />
        <img
          id="hiwMk1"
          src={HIW_MK1}
          alt=""
          aria-hidden="true"
          className="hidden"
          style={{ display: 'none' }}
        />
        <img
          id="hiwMk2"
          src={HIW_MK2}
          alt=""
          aria-hidden="true"
          className="hidden"
          style={{ display: 'none' }}
        />

        <div
          id="hiw"
          className="hiw__grid grid grid-cols-3 gap-[clamp(28px,3.6vw,52px)] items-start mb-0 max-[800px]:grid-cols-1 max-[800px]:gap-[clamp(40px,9vw,64px)] max-[800px]:max-w-115 max-[800px]:mx-auto"
        >
          {/* Step 1 */}
          <article
            data-step
            tabIndex={0}
            className="hstep group is-active relative grid gap-0 cursor-pointer outline-none min-w-0 max-[800px]:gap-0 focus-visible:outline-2 focus-visible:outline-(--punk)"
          >
            <div className="hstep__slab relative rounded-xl p-1.25 pb-8.25 bg-[#ECECE9] shadow-[0_0_0_1px_#D6D6D3,inset_0_0_0_1px_#FBFBF9,0_1px_2px_rgba(20,20,20,0.04),0_10px_28px_-10px_rgba(20,20,20,0.14)] transition-[box-shadow,transform] duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-[.is-active]:-translate-y-0.75 group-[.is-active]:shadow-[0_0_0_1px_#CFCFCB,inset_0_0_0_1px_#FBFBF9,0_1px_2px_rgba(20,20,20,0.05),0_16px_36px_-12px_rgba(20,20,20,0.2)] max-[800px]:pb-1.25 max-[800px]:mb-0">
              <i className="hstep__mat hidden" aria-hidden="true"></i>
              <div
                data-stage
                className="hstage relative z-1 aspect-square rounded-lg bg-[#FAFAF7] overflow-hidden max-w-none shadow-[0_0_0_1px_#D8D8D5] opacity-45 transition-[opacity,box-shadow] duration-800 ease-out group-[.is-active]:opacity-100 group-[.is-active]:shadow-[0_0_0_1px_#CFCFCB]"
              >
                <canvas className="absolute inset-0 w-full h-full block rounded-[inherit]"></canvas>
              </div>
            </div>
            <div
              data-track
              className="hstep__track relative h-[2px] bg-transparent mt-[26px] mb-[18px] mr-[12px] ml-0 overflow-hidden max-[800px]:m-0 max-[800px]:h-0"
            >
              <i className="hidden not-italic"></i>
            </div>
            <div className="hstep__body relative pt-5.5 mt-0 pb-0 pr-[12px] max-[800px]:pt-4.5 max-[800px]:mt-0 before:content-[''] before:absolute before:top-0 before:h-px before:bg-(--line) before:left-0 before:right-[calc(-0.5*clamp(28px,3.6vw,52px)-1px)] max-[800px]:before:hidden after:content-[''] after:absolute after:left-0 after:-top-1 after:w-2.25 after:h-2.25 after:rounded-full after:bg-white after:shadow-[0_0_0_1.5px_var(--line)] after:transition-[background,box-shadow] after:duration-300 group-[.is-active]:after:bg-(--punk) group-[.is-active]:after:shadow-[0_0_0_1.5px_var(--punk),0_0_0_5px_rgba(240,45,138,0.14)] max-[800px]:after:hidden">
              <div className="hstep__num font-mono font-medium text-[12px] leading-none tracking-[0.01em] uppercase text-(--muted) ml-[18px] max-[800px]:ml-0 transition-colors duration-400 group-[.is-active]:text-(--punk)">
                01 — Describe
              </div>
              <h3 className="font-display font-semibold text-[clamp(19px,1.8vw,23px)] leading-[1.2] tracking-[-0.015em] text-(--muted) mt-[6px] mb-0 transition-colors duration-400 group-[.is-active]:text-(--ink)">
                Choose who you want to reach
              </h3>
              <p className="m-0 mt-[8px] text-(--muted) text-[15px] leading-[1.55] max-w-[36ch] transition-colors duration-400 group-[.is-active]:text-(--ink-2)">
                Describe the places your customers visit.
              </p>
            </div>
          </article>

          {/* Step 2 */}
          <article
            data-step
            tabIndex={0}
            className="hstep group relative grid gap-0 cursor-pointer outline-none min-w-0 max-[800px]:gap-0 focus-visible:outline-2 focus-visible:outline-(--punk)"
          >
            <div className="hstep__slab relative rounded-[12px] p-[5px] pb-[33px] bg-[#ECECE9] shadow-[0_0_0_1px_#D6D6D3,inset_0_0_0_1px_#FBFBF9,0_1px_2px_rgba(20,20,20,0.04),0_10px_28px_-10px_rgba(20,20,20,0.14)] transition-[box-shadow,transform] duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-[.is-active]:-translate-y-[3px] group-[.is-active]:shadow-[0_0_0_1px_#CFCFCB,inset_0_0_0_1px_#FBFBF9,0_1px_2px_rgba(20,20,20,0.05),0_16px_36px_-12px_rgba(20,20,20,0.2)] max-[800px]:pb-[5px] max-[800px]:mb-0">
              <i className="hstep__mat hidden" aria-hidden="true"></i>
              <div
                data-stage
                className="hstage relative z-1 aspect-square rounded-[8px] bg-[#FAFAF7] overflow-hidden max-w-none shadow-[0_0_0_1px_#D8D8D5] opacity-45 transition-[opacity,box-shadow] duration-800 ease-out group-[.is-active]:opacity-100 group-[.is-active]:shadow-[0_0_0_1px_#CFCFCB]"
              >
                <canvas className="absolute inset-0 w-full h-full block rounded-[inherit]"></canvas>
              </div>
            </div>
            <div
              data-track
              className="hstep__track relative h-[2px] bg-transparent mt-[26px] mb-[18px] mr-[12px] ml-0 overflow-hidden max-[800px]:m-0 max-[800px]:h-0"
            >
              <i className="hidden not-italic"></i>
            </div>
            <div className="hstep__body relative pt-[22px] mt-0 pb-0 pr-[12px] max-[800px]:pt-[18px] max-[800px]:mt-0 before:content-[''] before:absolute before:top-0 before:h-[1px] before:bg-(--line) before:left-[calc(-0.5*clamp(28px,3.6vw,52px)-1px)] before:right-[calc(-0.5*clamp(28px,3.6vw,52px)-1px)] max-[800px]:before:hidden after:content-[''] after:absolute after:left-0 after:-top-[4px] after:w-[9px] after:h-[9px] after:rounded-full after:bg-white after:shadow-[0_0_0_1.5px_var(--line)] after:transition-[background,box-shadow] after:duration-300 group-[.is-active]:after:bg-(--punk) group-[.is-active]:after:shadow-[0_0_0_1.5px_var(--punk),0_0_0_5px_rgba(240,45,138,0.14)] max-[800px]:after:hidden">
              <div className="hstep__num font-mono font-medium text-[12px] leading-none tracking-[0.01em] uppercase text-(--muted) ml-[18px] max-[800px]:ml-0 transition-colors duration-400 group-[.is-active]:text-(--punk)">
                02 — Resolve
              </div>
              <h3 className="font-display font-semibold text-[clamp(19px,1.8vw,23px)] leading-[1.2] tracking-[-0.015em] text-(--muted) mt-[6px] mb-0 transition-colors duration-400 group-[.is-active]:text-(--ink)">
                Review your audience
              </h3>
              <p className="m-0 mt-[8px] text-(--muted) text-[15px] leading-[1.55] max-w-[36ch] transition-colors duration-400 group-[.is-active]:text-(--ink-2)">
                Punk finds devices that visited your chosen places and groups them into your audience.
              </p>
            </div>
          </article>

          {/* Step 3 */}
          <article
            data-step
            tabIndex={0}
            className="hstep group relative grid gap-0 cursor-pointer outline-none min-w-0 max-[800px]:gap-0 focus-visible:outline-2 focus-visible:outline-(--punk)"
          >
            <div className="hstep__slab relative rounded-[12px] p-[5px] pb-[33px] bg-[#ECECE9] shadow-[0_0_0_1px_#D6D6D3,inset_0_0_0_1px_#FBFBF9,0_1px_2px_rgba(20,20,20,0.04),0_10px_28px_-10px_rgba(20,20,20,0.14)] transition-[box-shadow,transform] duration-500 ease-[cubic-bezier(.2,.8,.2,1)] group-[.is-active]:-translate-y-[3px] group-[.is-active]:shadow-[0_0_0_1px_#CFCFCB,inset_0_0_0_1px_#FBFBF9,0_1px_2px_rgba(20,20,20,0.05),0_16px_36px_-12px_rgba(20,20,20,0.2)] max-[800px]:pb-[5px] max-[800px]:mb-0">
              <i className="hstep__mat hidden" aria-hidden="true"></i>
              <div
                data-stage
                className="hstage relative z-1 aspect-square rounded-[8px] bg-[#FAFAF7] overflow-hidden max-w-none shadow-[0_0_0_1px_#D8D8D5] opacity-45 transition-[opacity,box-shadow] duration-800 ease-out group-[.is-active]:opacity-100 group-[.is-active]:shadow-[0_0_0_1px_#CFCFCB]"
              >
                <canvas className="absolute inset-0 w-full h-full block rounded-[inherit]"></canvas>
              </div>
            </div>
            <div
              data-track
              className="hstep__track relative h-[2px] bg-transparent mt-[26px] mb-[18px] mr-[12px] ml-0 overflow-hidden max-[800px]:m-0 max-[800px]:h-0"
            >
              <i className="hidden not-italic"></i>
            </div>
            <div className="hstep__body relative pt-[22px] mt-0 pb-0 pr-3 max-[800px]:pt-4.5 max-[800px]:mt-0 before:content-[''] before:absolute before:top-0 before:h-px before:bg-(--line) before:left-[calc(-0.5*clamp(28px,3.6vw,52px)-1px)] before:right-0 max-[800px]:before:hidden after:content-[''] after:absolute after:left-0 after:-top-1 after:w-2.25 after:h-2.25 after:rounded-full after:bg-white after:shadow-[0_0_0_1.5px_var(--line)] after:transition-[background,box-shadow] after:duration-300 group-[.is-active]:after:bg-(--punk) group-[.is-active]:after:shadow-[0_0_0_1.5px_var(--punk),0_0_0_5px_rgba(240,45,138,0.14)] max-[800px]:after:hidden">
              <div className="hstep__num font-mono font-medium text-[12px] leading-none tracking-[0.01em] uppercase text-(--muted) ml-[18px] max-[800px]:ml-0 transition-colors duration-400 group-[.is-active]:text-(--punk)">
                03 — Launch
              </div>
              <h3 className="font-display font-semibold text-[clamp(19px,1.8vw,23px)] leading-[1.2] tracking-[-0.015em] text-(--muted) mt-[6px] mb-0 transition-colors duration-400 group-[.is-active]:text-(--ink)">
                Launch your ad
              </h3>
              <p className="m-0 mt-2 text-(--muted) text-[15px] leading-[1.55] max-w-[36ch] transition-colors duration-400 group-[.is-active]:text-(--ink-2)">
                Add your image or video, choose your budget, and publish through Punk.
              </p>
            </div>
          </article>
        </div>
      </div>
    </section>
  );
}

export default HowItWorksSection;
