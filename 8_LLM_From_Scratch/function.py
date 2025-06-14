import torch
import numpy as np

def softmax(x: torch.Tensor, dim: int) -> torch.Tensor:
    """
    Args:
        x: torch.Tensor, input tensor of any shape
        dim: int, dimension along which to apply softmax
        
    Returns:
        torch.Tensor, output tensor of the same shape as input with softmax applied along dim
    """
    max_val = torch.max(x, dim=dim, keepdim=True)[0]
    x_shifted = x - max_val
    exp_x = torch.exp(x_shifted)

    return exp_x / torch.sum(exp_x, dim=dim, keepdim=True)

def scaled_dot_product_attention(Q: torch.Tensor, K: torch.Tensor, V: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
    """
    Args:
        Q: torch.Tensor, query tensor of shape (..., seq_len_q, d_k)
        K: torch.Tensor, key tensor of shape (..., seq_len_k, d_k)
        V: torch.Tensor, value tensor of shape (..., seq_len_v, d_v)
        mask: torch.Tensor | None, optional boolean mask of shape (..., seq_len_q, seq_len_k)
    
    Returns:
        torch.Tensor, output tensor of shape (..., seq_len_q, d_v)
    """
    d_k = Q.shape[-1]

    scaled = torch.einsum('...qd,...kd->...qk', Q, K) / (d_k ** 0.5)

    if mask is not None:
        scaled = scaled.masked_fill(mask == 0, float('-inf'))

    attention = softmax(scaled, dim=-1)
    return torch.einsum('...qk,...kv->...qv', attention, V)

def cross_entropy(logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
    """
    Args:
        logits: torch.Tensor, predicted logits of shape (..., vocab_size)
        targets: torch.Tensor, target indices of shape (...)
    
    Returns:
        torch.Tensor, average cross-entropy loss across batch dimensions
    """
    vocab_dim = -1

    max_logits = torch.max(logits, dim=vocab_dim, keepdim=True)[0]
    shifted_logits = logits - max_logits

    # Compute log-softmax directly to avoid separate exp and log
    log_probs = shifted_logits - torch.logsumexp(shifted_logits, dim=vocab_dim, keepdim=True)

    loss = -log_probs.gather(dim=vocab_dim, index=targets.unsqueeze(vocab_dim)).squeeze(vocab_dim)
    return loss.mean()

def get_learning_rate(t: int, alpha_max: float, alpha_min: float, T_w: int, T_c: int) -> float:
    """
    Compute the learning rate αt according to the cosine learning rate schedule with warmup.
    
    Args:
        t (int): Current training step.
        alpha_max (float): Maximum learning rate.
        alpha_min (float): Minimum learning rate.
        T_w (int): Number of warm-up iterations.
        T_c (int): Total number of cosine annealing iterations.
    
    Returns:
        float: The learning rate αt for the current step t.
    """
    if t < T_w: # Warm-up
        return (t / T_w) * alpha_max
    elif T_w <= t <= T_c: # Cosine annealing
        return alpha_min + 0.5 * (1 + torch.cos(torch.tensor((t - T_w) / (T_c - T_w) * torch.pi, dtype=torch.float64))) * (alpha_max - alpha_min)
    elif t > T_c: # Post-annealing
        return alpha_min

def clip_gradient(parameters, max_norm):
    total_norm = 0
    for p in parameters:
        if p.grad is not None:
            total_norm += p.grad.pow(2).sum()
    total_norm = total_norm.sqrt().item()
    clip_coef = max_norm / (total_norm + 1e-6)
    if clip_coef < 1:
        for p in parameters:
            if p.grad is not None:
                p.grad.data.mul_(clip_coef)

def data_loader(dataset, batch_size, context_length, device):
    n = len(dataset)
    indices = np.random.randint(0, n - context_length, size=batch_size)

    inputs = torch.zeros((batch_size, context_length), dtype=torch.long, device=device)
    outputs = torch.zeros((batch_size, context_length), dtype=torch.long, device=device)

    for idx, indice  in enumerate(indices):
        inputs[idx] = torch.from_numpy(dataset[indice : indice + context_length])
        outputs[idx] = torch.from_numpy(dataset[indice + 1 : indice + context_length + 1])
    
    return inputs, outputs

def save_checkpoint(model, optimizer, iteration, out):
    state_dict = {
        'model_state_dict' : model.state_dict(),
        'optimizer_state_dict' : optimizer.state_dict(),
        'iteration' : iteration
    }
    
    torch.save(state_dict, out)

def load_checkpoint(src, model, optimizer):
    state_dict = torch.load(src)

    model.load_state_dict(state_dict['model_state_dict'])
    optimizer.load_state_dict(state_dict['optimizer_state_dict'])
    iteration = state_dict['iteration']

    return iteration

def nucleus_sampling_decoder(model, tokenizer, prompt, max_length=100, temperature=1.0, p=0.9, device='cuda:0'):
    model.eval()

    prompt_tokens = tokenizer.encode(prompt)
    input_ids = torch.tensor(prompt_tokens, dtype=torch.long, device=device).unsqueeze(0)  # Shape: (1, seq_len)
    generated_ids = input_ids.clone()
    eot_id = tokenizer.encode("<|endoftext|>")[0]

    with torch.no_grad():
        for _ in range(max_length - input_ids.shape[1]):
            logits = model(generated_ids)[:, -1, :]  # Shape: (1, vocab_size)
            logits = logits / temperature
            probs = softmax(logits, dim=-1).squeeze(0) # Shape: (vocab_size,)

            # Nucleus sampling
            sorted_probs, sorted_indices = torch.sort(probs, descending=True)
            cumsum = torch.cumsum(sorted_probs, dim=0)
            nucleus_mask = cumsum <= p
            nucleus_indices = sorted_indices[nucleus_mask]
            nucleus_probs = sorted_probs[nucleus_mask]

            if nucleus_probs.numel() == 0:
                nucleus_probs = sorted_probs[:1]  # Take the top-1 probability
                nucleus_indices = sorted_indices[:1]  # Take the top-1 index


            nucleus_probs = nucleus_probs / (nucleus_probs.sum() + 1e-10)
            next_token = torch.multinomial(nucleus_probs, num_samples=1)
            next_token_id = nucleus_indices[next_token].item()

            # Append to generated sequence
            generated_ids = torch.cat(
                [generated_ids, torch.tensor([[next_token_id]], device=device)], dim=1
            )
            if next_token_id == eot_id:
                break
                
    return tokenizer.decode(generated_ids.squeeze(0).tolist()).replace('<|endoftext|>', '').strip()