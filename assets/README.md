# assets/

行情视频用到的静态素材。

## bgm.mp3 —— 背景音乐

一段低调、不抢戏的环境垫乐，压到很低的音量铺在配音底下（见
`renderers/audio.py` 的 `BGM_VOLUME`）。视频渲染时由 `renderers/encode.py`
用 ffmpeg 的 `amix` 循环叠加进成片；文件缺失则自动跳过、只留配音或静音。

### 来源与授权

**本仓库自制、置于公有领域（CC0 1.0）。** 不是第三方曲目，没有署名或版权
牵连——用一组正弦音合成的一段舒缓大三和弦垫乐，纯机器生成、无采样、无演奏，
可任意使用、修改、商用、再发布，无需署名。

之所以自制而非选用外部 CC0 曲目：早先计划取自 FreePD.com，但该站已关闭；
与其引一段来源存疑的音频，不如自制一段可复现、授权干净的垫乐。

### 复现 / 替换

用任意 ffmpeg（系统装的，或 `imageio-ffmpeg` 自带的二进制）重新生成：

```bash
ffmpeg -y \
  -f lavfi -i "sine=frequency=130.81:duration=40" \
  -f lavfi -i "sine=frequency=164.81:duration=40" \
  -f lavfi -i "sine=frequency=196.00:duration=40" \
  -f lavfi -i "sine=frequency=261.63:duration=40" \
  -filter_complex "[0][1][2][3]amix=inputs=4,\
tremolo=f=0.12:d=0.4,lowpass=f=1600,aecho=0.8:0.85:70:0.3,volume=1.6,\
afade=t=in:st=0:d=4,afade=t=out:st=36:d=4[a]" \
  -map "[a]" -ac 2 -ar 44100 -b:a 128k assets/bgm.mp3
```

频率对应 C3–E3–G3–C4 的 C 大三和弦；`amix` 把四路正弦相加取平均（不写
`normalize`——`imageio-ffmpeg` 自带的 ffmpeg 4.2.2 不认这个选项），`volume=1.6`
把响度提回来；`tremolo` 给一层缓慢的音量起伏，`lowpass`+`aecho` 让音色暖而不刺，
两端 `afade` 让循环衔接不突兀。

想换成别的曲子：把任意音频命名为 `bgm.mp3` 放这里即可，或用环境变量
`MARKET_BGM` 指向别处的文件。**若换用第三方曲目，务必确认其授权允许商用与
再发布，并在此处更新来源与授权说明。**
