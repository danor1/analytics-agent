import matplotlib.pyplot as plt
import matplotlib.image as mpimg
import io

def render(graph):
    try:
        img_bytes = graph.get_graph().draw_mermaid_png()
        image = mpimg.imread(io.BytesIO(img_bytes), format='png')
        plt.imshow(image)
        plt.axis('off')
        plt.show()
    except Exception as e:
        print("Could not render graph:", e)
